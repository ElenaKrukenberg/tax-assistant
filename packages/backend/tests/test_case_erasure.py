"""Erasing user data: what is cleared, in what order, and what survives a failure.

Two operations, kept apart on purpose. Deleting a case clears the tables and the
paused run; forgetting a person clears the profile memory that outlives every case.
Neither implies the other, which is the whole of ADR 0011 made callable.

Offline. All three stores are faked, because what these tests are about is not SQL but
the sequence: which store is emptied first, what is left behind when the second one
refuses, and whether a caller can safely try again. The real tables and the real
checkpoint are checked in `test_cases_api.py`, which needs a database.

Three, not two: besides the tables and the interview's checkpoint there is one intake
run per uploaded document. It arrived with document intake, after this module was
written, and until it was faked here too `retention.forget_every_run` reached a real
database from a test that claims to be offline - so `pytest` opened a connection to
whatever DATABASE_URL happened to point at, and failed outright without one.

The lock has a section of its own at the bottom. It exists to stop an interview
writing a checkpoint after a delete has already reported success, so "released on
every path" is not a detail here - a lock that leaks holds a case shut until the
process restarts.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from agents import profile_memory
from agents.graph import case_thread_id
from core.case_lock import CaseBusy, hold, lock_for
from db import cases
from services import case_erasure, profile_erasure
from services.documents import retention

USER = str(uuid.uuid4())
CASE = str(uuid.uuid4())
NOW = datetime.now(timezone.utc)


def run(coro):
    return asyncio.run(coro)


class FakeSaver:
    """Stands in for AsyncPostgresSaver: records deletions, or refuses them."""

    def __init__(self, refuse: bool = False):
        self.deleted: list[str] = []
        self.refuse = refuse

    async def adelete_thread(self, thread_id: str) -> None:
        if self.refuse:
            raise RuntimeError("the checkpoint tables refused")
        self.deleted.append(thread_id)


@pytest.fixture
def stores(monkeypatch):
    """All three stores faked, plus the running order they were touched in."""
    order: list[str] = []
    saver = FakeSaver()
    existing = {CASE}

    async def checkpointer():
        return saver

    def get_case(user_id, case_id):
        if case_id not in existing:
            raise cases.CaseNotFound(case_id)
        return cases.TaxCase(id=case_id, tax_year=2025, status="gathering",
                             created_at=NOW, updated_at=NOW)

    def delete_case(user_id, case_id):
        if case_id not in existing:
            raise cases.CaseNotFound(case_id)
        existing.discard(case_id)
        order.append("tables")

    async def deleting(thread_id):
        order.append("checkpoint")
        saver.deleted.append(thread_id)

    async def forget_every_run(user_id, case_id):
        order.append("documents")

    monkeypatch.setattr(case_erasure, "checkpointer", checkpointer)
    monkeypatch.setattr(retention, "forget_every_run", forget_every_run)
    monkeypatch.setattr(cases, "get_case", get_case)
    monkeypatch.setattr(cases, "delete_case", delete_case)
    monkeypatch.setattr(saver, "adelete_thread", deleting)
    return {"order": order, "saver": saver, "existing": existing}


# --- the order, and what a failure leaves behind ----------------------------------

def test_the_checkpoint_is_cleared_before_the_tables(stores):
    """The order is the whole argument of the module, so it is asserted directly.

    Tables first would delete the case the user can see and strand their answers in
    graph state - the bug this replaced.
    """
    run(case_erasure.erase_case(USER, CASE))
    assert stores["order"] == ["checkpoint", "documents", "tables"]
    assert stores["saver"].deleted == [f"{USER}:{CASE}"]


def test_a_refused_checkpoint_leaves_the_tables_untouched(stores, monkeypatch):
    """Nothing deleted, an error raised, and the next attempt starts from scratch."""
    async def refuse(thread_id):
        raise RuntimeError("the checkpoint tables refused")

    monkeypatch.setattr(stores["saver"], "adelete_thread", refuse)
    with pytest.raises(RuntimeError):
        run(case_erasure.erase_case(USER, CASE))
    assert stores["order"] == []
    assert CASE in stores["existing"], "the case must survive a failed delete"


def test_a_refused_table_delete_raises_and_a_retry_finishes(stores, monkeypatch):
    """The half-done state is recoverable, which is why retrying has to be safe.

    The checkpoint is gone and the case is not. The user sees an error, the case is
    still theirs to delete, and the second attempt clears an already-empty checkpoint
    without complaint.
    """
    def refuse(user_id, case_id):
        raise RuntimeError("the tables refused")

    monkeypatch.setattr(cases, "delete_case", refuse)
    with pytest.raises(RuntimeError):
        run(case_erasure.erase_case(USER, CASE))
    assert stores["order"] == ["checkpoint", "documents"]

    deleted = []
    monkeypatch.setattr(cases, "delete_case",
                        lambda u, c: deleted.append(c))
    run(case_erasure.erase_case(USER, CASE))
    assert deleted == [CASE]


def test_an_unknown_case_touches_neither_store(stores):
    """A stranger's id and a deleted id look the same, and both stop at the door."""
    with pytest.raises(cases.CaseNotFound):
        run(case_erasure.erase_case(USER, str(uuid.uuid4())))
    assert stores["order"] == []


def test_deleting_the_same_case_twice_is_a_not_found(stores):
    """The chosen contract: the second call reports there is no such case.

    204 both times would also be defensible - DELETE is idempotent by effect - but
    the route has always answered a case this user does not have with 404, and this
    pins that rather than quietly changing it.
    """
    run(case_erasure.erase_case(USER, CASE))
    with pytest.raises(cases.CaseNotFound):
        run(case_erasure.erase_case(USER, CASE))


def test_a_finalized_case_can_still_be_deleted(stores, monkeypatch):
    """Approving a report must not trap the data it was made from.

    `delete_case` deliberately does not go through `_require_open`: a finalized case
    is read-only, not undeletable.
    """
    monkeypatch.setattr(
        cases, "get_case",
        lambda u, c: cases.TaxCase(id=c, tax_year=2025, status="finalized",
                                   created_at=NOW, updated_at=NOW, finalized_at=NOW))
    run(case_erasure.erase_case(USER, CASE))
    assert stores["order"] == ["checkpoint", "documents", "tables"]


def test_the_profile_memory_is_never_opened(stores, monkeypatch):
    """Deleting a case may not forget the person (ADR 0011).

    Asserted by making the store explode if anything reaches for it, rather than by
    reading the source: the point is that no code path opens it, including the ones
    a future edit might add.
    """
    async def explode():
        raise AssertionError("erasing a case must not touch the profile memory")

    monkeypatch.setattr(profile_memory, "store", explode)
    run(case_erasure.erase_case(USER, CASE))


# --- deleting every case ----------------------------------------------------------

def test_erase_all_clears_every_case_and_reports_nothing_left(stores, monkeypatch):
    others = [str(uuid.uuid4()) for _ in range(3)]
    stores["existing"].update(others)
    monkeypatch.setattr(
        cases, "list_cases",
        lambda u: [cases.TaxCase(id=c, tax_year=2020 + i, status="gathering",
                                 created_at=NOW, updated_at=NOW)
                   for i, c in enumerate([CASE, *others])])

    assert run(case_erasure.erase_all_cases(USER)) == []
    assert stores["order"] == ["checkpoint", "documents", "tables"] * 4
    assert stores["existing"] == set()


def test_erase_all_goes_on_past_a_case_it_cannot_delete(stores, monkeypatch):
    """One stuck case must not stand between the user and deleting the rest."""
    stubborn = str(uuid.uuid4())
    good = str(uuid.uuid4())
    stores["existing"].update({stubborn, good})
    monkeypatch.setattr(
        cases, "list_cases",
        lambda u: [cases.TaxCase(id=c, tax_year=2020 + i, status="gathering",
                                 created_at=NOW, updated_at=NOW)
                   for i, c in enumerate([stubborn, good])])

    async def selective(thread_id):
        if thread_id.endswith(stubborn):
            raise RuntimeError("this one refuses")
        stores["order"].append("checkpoint")

    monkeypatch.setattr(stores["saver"], "adelete_thread", selective)

    failed = run(case_erasure.erase_all_cases(USER))
    assert failed == [stubborn]
    assert good not in stores["existing"], "the healthy case was deleted anyway"


# --- the thread id ----------------------------------------------------------------

def test_the_thread_id_format_is_frozen():
    """Every paused interview in `checkpoints` is filed under this exact string.

    Changing the format without a migration orphans all of them at once, and the
    orphans are invisible: the interview would simply start over and the old rows
    would sit there holding tax answers nothing can reach.
    """
    assert case_thread_id("u", "c") == "u:c"


# --- the lock ---------------------------------------------------------------------

def test_two_operations_on_one_case_do_not_interleave():
    """The race this whole mechanism exists for, in miniature."""
    async def scenario():
        seen: list[str] = []

        async def worker(name: str):
            async with hold("case", timeout=5):
                seen.append(f"{name}:in")
                await asyncio.sleep(0.01)
                seen.append(f"{name}:out")

        await asyncio.gather(worker("a"), worker("b"))
        return seen

    seen = run(scenario())
    assert seen in (["a:in", "a:out", "b:in", "b:out"],
                    ["b:in", "b:out", "a:in", "a:out"])


def test_the_lock_is_released_when_the_block_raises():
    async def scenario():
        with pytest.raises(ValueError):
            async with hold("raises", timeout=5):
                raise ValueError("boom")
        return lock_for("raises").locked()

    assert run(scenario()) is False


def test_the_lock_is_released_when_the_holder_is_cancelled():
    """A disconnected client cancels the task; the case must not stay shut."""
    async def scenario():
        started = asyncio.Event()

        async def holder():
            async with hold("cancelled", timeout=5):
                started.set()
                await asyncio.sleep(10)

        task = asyncio.create_task(holder())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return lock_for("cancelled").locked()

    assert run(scenario()) is False


def test_a_case_that_stays_busy_times_out_rather_than_hanging():
    async def scenario():
        held = asyncio.Event()

        async def holder():
            async with hold("busy", timeout=5):
                held.set()
                await asyncio.sleep(1)

        task = asyncio.create_task(holder())
        await held.wait()
        with pytest.raises(CaseBusy):
            async with hold("busy", timeout=0.05):
                pass  # pragma: no cover
        task.cancel()

    run(scenario())


def test_two_callers_get_the_same_lock_and_two_cases_get_two():
    """A weak dictionary must not hand a waiter a lock nobody else is holding."""
    async def scenario():
        first = lock_for("same")
        async with hold("same", timeout=5):
            assert lock_for("same") is first
            assert first.locked()
            assert not lock_for("other").locked()

    run(scenario())


def test_a_busy_case_does_not_block_a_different_one():
    async def scenario():
        held = asyncio.Event()

        async def holder():
            async with hold("one", timeout=5):
                held.set()
                await asyncio.sleep(1)

        task = asyncio.create_task(holder())
        await held.wait()
        async with hold("two", timeout=0.05):
            pass
        task.cancel()

    run(scenario())


# --- forgetting the person, which is the other operation ---------------------------

class FakeItem:
    def __init__(self, key):
        self.key = key
        self.value = {"value": 1, "tax_year": 2025}


class FakeStore:
    """Stands in for AsyncPostgresStore: one namespace, pageable, deletable."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.namespaces: list[tuple] = []

    async def asearch(self, namespace, limit=100):
        self.namespaces.append(namespace)
        return [FakeItem(k) for k in self.keys[:limit]]

    async def adelete(self, namespace, key):
        self.keys.remove(key)


def test_forgetting_takes_every_key_in_the_namespace(monkeypatch):
    """Including keys this release no longer carries.

    `profile_memory.recall` skips a key that left `domain/fields.py`, which is not
    the same as it being gone - it is still something the system remembers about a
    person, and "forget me" has to mean it.
    """
    store = FakeStore(["commute.distance_km", "a_key_from_an_old_release"])

    async def opened():
        return store

    monkeypatch.setattr(profile_memory, "store", opened)
    assert run(profile_erasure.forget_profile(USER)) == 2
    assert store.keys == []
    assert store.namespaces[0] == (USER, "profile")


def test_forgetting_pages_through_a_namespace_larger_than_one_page(monkeypatch):
    store = FakeStore([f"k{i}" for i in range(250)])

    async def opened():
        return store

    monkeypatch.setattr(profile_memory, "store", opened)
    assert run(profile_erasure.forget_profile(USER)) == 250
    assert store.keys == []


def test_forgetting_nothing_is_a_success_not_an_error(monkeypatch):
    """They asked for there to be nothing remembered, and there is nothing."""
    store = FakeStore([])

    async def opened():
        return store

    monkeypatch.setattr(profile_memory, "store", opened)
    assert run(profile_erasure.forget_profile(USER)) == 0


def test_forgetting_and_an_interview_cannot_run_at_the_same_time():
    """The same resurrection the case erasure prevents, in the store it leaves alone.

    An advance teaches the memory as it goes, so it holds this lock too - after its
    own case lock, always in that order, which is what stops the pair deadlocking.
    """
    async def scenario():
        key = profile_erasure.profile_lock_key(USER)
        held = asyncio.Event()

        async def advancing():
            async with hold(case_thread_id(USER, CASE), timeout=5), hold(key, timeout=5):
                held.set()
                await asyncio.sleep(1)

        task = asyncio.create_task(advancing())
        await held.wait()
        with pytest.raises(CaseBusy):
            async with hold(key, timeout=0.05):
                pass  # pragma: no cover
        task.cancel()

    run(scenario())


def test_erasing_a_case_does_not_take_the_profile_lock():
    """The two are separate choices, so they must not queue behind each other."""
    async def scenario():
        async with hold(profile_erasure.profile_lock_key(USER), timeout=5):
            # A case delete must still be able to start while a forget is running.
            async with hold(case_thread_id(USER, CASE), timeout=0.05):
                pass

    run(scenario())
