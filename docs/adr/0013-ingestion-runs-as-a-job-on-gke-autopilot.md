# Ingestion runs as a Kubernetes Job on GKE Autopilot

Accepted 2 September 2026. **Not yet implemented**: the work is scheduled after the
15 September hand-in. Until then ingestion runs by hand from a laptop, as the
release procedure in `packages/backend/db/README.md` describes.

KB ingestion is a batch job that runs for minutes once every few weeks: it reads
`KB/`, embeds every chunk and writes the corpus into Postgres inside one
transaction. Nothing about it wants a server. A permanent virtual machine sized for
it would idle away 99.9% of the month, and the alternative already in place —
running it from a laptop — is correct but reproducible by nobody else.

So it becomes a Kubernetes `Job` on GKE Autopilot. `Job` is the built-in Kubernetes
object for exactly this shape: a program that starts, does its work, exits, and is
then removed. Autopilot bills **pod resource requests** rather than node capacity,
per second with a one-minute minimum, so idle capacity is never billed at all and a
monthly run costs cents of compute. `Dockerfile.ingest` is the portable unit: the
same image runs unchanged as a Cloud Run Job or an ECS task if the platform ever
changes, which is the whole reason ingestion gets an image of its own rather than
sharing the API's.

The cluster fee is $0.10 per hour — $74.40 a month — and GKE's free tier issues
exactly $74.40 in monthly credits per billing account, enough for one Autopilot
cluster. That credit covers the cluster fee only; it does not apply to compute. So
the honest claim is "free cluster, cents per run", not "zero cost", and a **second**
cluster on the same billing account is billed in full.

Two constraints follow. Autopilot clusters are always regional, so the region is a
deliberate choice rather than a default: `europe-west3` (Frankfurt), where the users
are and where the rest of the deployment already sits. And the API does **not**
move — it stays on Render with its native Python build from `render.yaml`. A
long-running pod would be billed around the clock and would give up a working free
plan for nothing this project needs.

This project is also a portfolio piece, and that is part of why Kubernetes is here
at all: the API has no scaling problem that Kubernetes solves. The Job is the one
place where Kubernetes fits the problem instead of the problem being bent to fit
Kubernetes, and it is the honest thing to say about the choice.
