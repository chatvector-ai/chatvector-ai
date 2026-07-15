import type { UploadInput } from "../models.js";

const MIME_BY_EXTENSION: Readonly<Record<string, string>> = {
  ".pdf": "application/pdf",
  ".txt": "text/plain",
};

/** Builds a fresh multipart body so the /ingest -> /upload fallback is safe. */
export async function createUploadFormData(
  input: UploadInput,
): Promise<FormData> {
  if (!input || typeof input !== "object") {
    throw new TypeError("upload input is required");
  }

  if ("path" in input) {
    return createPathFormData(input);
  }
  if ("data" in input) {
    return createMemoryFormData(input);
  }

  throw new TypeError("upload input must provide path or replayable data");
}

async function createPathFormData(
  input: Extract<UploadInput, { path: string }>,
): Promise<FormData> {
  if (typeof input.path !== "string" || input.path.trim().length === 0) {
    throw new TypeError("path must be a non-empty string");
  }

  const [{ openAsBlob }, path] = await Promise.all([
    import("node:fs"),
    import("node:path"),
  ]);
  const fileName = path.basename(input.path);
  const contentType = chooseContentType(
    input.contentType,
    undefined,
    fileName,
  );
  const blob = await openAsBlob(input.path, { type: contentType });
  return formDataWithFile(blob, fileName);
}

function createMemoryFormData(
  input: Extract<UploadInput, { data: Uint8Array | Blob }>,
): FormData {
  if (typeof input.fileName !== "string" || input.fileName.trim().length === 0) {
    throw new TypeError("fileName must be a non-empty string");
  }
  if (!(input.data instanceof Uint8Array) && !(input.data instanceof Blob)) {
    throw new TypeError("data must be a Uint8Array or Blob");
  }

  const existingType = input.data instanceof Blob ? input.data.type : undefined;
  const contentType = chooseContentType(
    input.contentType,
    existingType,
    input.fileName,
  );
  let blob: Blob;
  if (input.data instanceof Blob) {
    blob =
      input.data.type === contentType
        ? input.data
        : new Blob([input.data], { type: contentType });
  } else {
    const copy = new Uint8Array(input.data.byteLength);
    copy.set(input.data);
    blob = new Blob([copy], { type: contentType });
  }
  return formDataWithFile(blob, input.fileName);
}

function chooseContentType(
  explicit: string | undefined,
  existing: string | undefined,
  fileName: string,
): string {
  if (explicit?.trim()) {
    return explicit.trim();
  }
  if (existing?.trim()) {
    return existing.trim();
  }
  const dot = fileName.lastIndexOf(".");
  const extension = dot >= 0 ? fileName.slice(dot).toLowerCase() : "";
  return MIME_BY_EXTENSION[extension] ?? "application/octet-stream";
}

function formDataWithFile(blob: Blob, fileName: string): FormData {
  const form = new FormData();
  form.set("file", blob, fileName);
  return form;
}
