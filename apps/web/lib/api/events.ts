// The events an answer is built from: those of the /ask stream, generated from the backend, and the
// two the client adds itself when the connection breaks or the user stops the answer.

import type { ErrorEvent, StreamEvent } from "@/lib/contracts";

export type ClientErrorEvent = Omit<ErrorEvent, "kind"> & { kind: "network" | "stopped" };

export type AskEvent = StreamEvent | ClientErrorEvent;
