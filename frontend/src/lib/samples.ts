import type { ApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { codeOf, explain, type JobResult, NETWORK } from "./jobs";

export type Sample = components["schemas"]["SampleSummary"];

export type SamplesResult = { ok: true; samples: Sample[] } | { ok: false; message: string };

/** Where the site serves a clip from: frontend/public/samples, written by backend/scripts/make_samples.py. */
export function clipUrl(id: string): string {
  return `/samples/${id}.wav`;
}

export async function fetchSamples(client: ApiClient): Promise<SamplesResult> {
  try {
    const { data, error, response } = await client.GET("/samples");
    if (data) return { ok: true, samples: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}

export async function startSampleJob(
  client: ApiClient,
  sampleId: string,
  callDate: string,
  speakerNames: string[],
): Promise<JobResult> {
  try {
    const { data, error, response } = await client.POST("/jobs", {
      body: { sample_id: sampleId, call_date: callDate, speaker_names: speakerNames },
    });
    if (data) return { ok: true, job: data };
    return { ok: false, message: explain(codeOf(error), response.headers.get("retry-after")) };
  } catch {
    return { ok: false, message: NETWORK };
  }
}
