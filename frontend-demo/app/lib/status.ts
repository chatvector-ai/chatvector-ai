import { API_BASE } from "./api";

export type ComponentHealth = {
  status: "ok" | "error";
  latency_ms?: number;
  error?: string;
  cached?: boolean;
  checked_at?: string;
};

export type SystemStatus = {
  status: "healthy" | "degraded" | "unhealthy";
  components: {
    api: string;
    database: string;
    queue: string;
    embeddings: string;
    llm: string;
  };
  health_checks: {
    embedding: ComponentHealth;
    llm: ComponentHealth;
    redis?: ComponentHealth;
  };
  metrics: {
    document_queue: number;
    workers_active: number;
    memory_usage: number;
    documents_indexed: number | null;
    total_queries: number | null;
  };
  uptime: string;
  version: string;
};

export async function getSystemStatus(): Promise<SystemStatus> {
  const res = await fetch(`${API_BASE}/status`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
    // Prevent Next.js from aggressively caching this client-side call
    cache: "no-store", 
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch status: ${res.statusText}`);
  }

  return (await res.json()) as SystemStatus;
}