import type { Job } from "@/lib/jobs";

const TEXT: Record<Job["status"], string> = {
  uploaded: "Starting…",
  transcribing: "Transcribing the recording…",
  analyzing: "Finding the commitments…",
  done: "Done.",
  failed: "That did not work.",
};

/** A polite live region, so a screen reader hears each stage without the page moving. */
export function JobStatus({
  status,
  message,
}: {
  status: Job["status"] | "submitting" | "uploading" | null;
  message?: string;
}) {
  const text =
    message ??
    (status === "submitting"
      ? "Sending…"
      : status === "uploading"
        ? "Uploading the recording…"
        : status
          ? TEXT[status]
          : "");
  return (
    <p role="status" aria-live="polite" className="status" data-busy={status !== null && status !== "done"}>
      {text}
    </p>
  );
}
