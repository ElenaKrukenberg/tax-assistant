import { cn } from "@/lib/utils";

export function Logo({ className, showWord = true }: { className?: string; showWord?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="relative flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-elevated">
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M4 6h16" />
          <path d="M4 12h10" />
          <path d="M4 18h16" />
          <circle cx="18" cy="12" r="2.2" fill="currentColor" stroke="none" />
        </svg>
      </div>
      {showWord && (
        <div className="flex items-baseline gap-1.5 leading-none">
          <span className="text-[15px] font-semibold tracking-tight text-foreground">Steuer</span>
          <span className="text-[15px] font-medium tracking-tight text-muted-foreground">
            Assist
          </span>
        </div>
      )}
    </div>
  );
}
