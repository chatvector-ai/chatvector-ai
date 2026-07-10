"use client";

import { useEffect, useState, useCallback } from "react";
import { RefreshCw, AlertCircle, CheckCircle2, ServerCrash, Clock, Database, BrainCircuit, Activity, Cpu } from "lucide-react";
import { getSystemStatus, StatusFetchError, statusErrorTitle, SystemStatus } from "../lib/status";

export default function StatusPage() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorTitle, setErrorTitle] = useState("Unable to Load Status");
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    setErrorTitle("Unable to Load Status");
    try {
      const data = await getSystemStatus();
      setStatus(data);
      setLastChecked(new Date());
    } catch (err: unknown) {
      if (err instanceof StatusFetchError) {
        setError(err.message);
        setErrorTitle(statusErrorTitle(err.kind));
      } else if (err instanceof Error) {
        setError(err.message || "Failed to reach backend.");
        setErrorTitle("Backend Unreachable");
      } else {
        setError("Failed to reach backend.");
        setErrorTitle("Backend Unreachable");
      }
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const getStatusColor = (state: string) => {
    switch (state) {
      case "healthy":
      case "ok":
      case "connected":
      case "online":
        return "text-green-500";
      case "degraded":
        return "text-yellow-500";
      case "unhealthy":
      case "error":
      case "disconnected":
        return "text-red-500";
      default:
        if (state.includes("connected")) return "text-green-500";
        if (state.includes("disconnected")) return "text-red-500";
        return "text-muted";
    }
  };

  const getStatusIcon = (state: string) => {
    switch (state) {
      case "healthy":
      case "ok":
      case "connected":
      case "online":
        return <CheckCircle2 className="h-5 w-5 text-green-500" />;
      case "degraded":
        return <AlertCircle className="h-5 w-5 text-yellow-500" />;
      case "unhealthy":
      case "error":
      case "disconnected":
        return <ServerCrash className="h-5 w-5 text-red-500" />;
      default:
        if (state.includes("connected")) return <CheckCircle2 className="h-5 w-5 text-green-500" />;
        if (state.includes("disconnected")) return <ServerCrash className="h-5 w-5 text-red-500" />;
        return <Activity className="h-5 w-5 text-muted" />;
    }
  };

  return (
    <div className="flex min-h-[calc(100dvh-60px)] w-full flex-col items-center bg-background p-4 sm:p-8">
      <div className="w-full max-w-4xl space-y-6">
        
        {/* Header */}
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-3xl font-bold text-foreground">System Status</h1>
            <p className="text-muted mt-1">
              {lastChecked 
                ? `Last checked: ${lastChecked.toLocaleTimeString()}`
                : "Checking system health..."}
            </p>
          </div>
          <button
            onClick={fetchStatus}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg bg-surface px-4 py-2 text-sm font-medium text-foreground border border-border hover:bg-accent/10 hover:text-accent transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {/* Loading / Error States */}
        {loading && !status && !error && (
          <div className="space-y-6 animate-pulse" aria-busy="true">
            <div className="flex items-center gap-4 rounded-xl border border-border bg-surface p-6">
              <div className="h-5 w-5 rounded-full bg-border" />
              <div className="space-y-2">
                <div className="h-5 w-28 rounded bg-border" />
                <div className="h-3 w-52 rounded bg-border" />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
                <div className="mb-4 h-3 w-40 rounded bg-border" />
                <div className="space-y-4">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <div
                      key={index}
                      className={`flex items-center justify-between ${
                        index < 4 ? "border-b border-border pb-3" : ""
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="h-4 w-4 rounded bg-border" />
                        <div className="h-4 w-24 rounded bg-border" />
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="h-3 w-16 rounded bg-border" />
                        <div className="h-5 w-5 rounded-full bg-border" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
                <div className="mb-4 h-3 w-36 rounded bg-border" />
                <div className="grid grid-cols-2 gap-4">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <div
                      key={index}
                      className="rounded-lg border border-border bg-background p-4"
                    >
                      <div className="mb-2 h-3 w-20 rounded bg-border" />
                      <div className="h-7 w-14 rounded bg-border" />
                      {index === 2 && (
                        <div className="mt-2 h-2 w-full rounded bg-border" />
                      )}
                    </div>
                  ))}
                </div>

                <div className="mt-6 space-y-3 border-t border-border pt-4">
                  <div className="flex items-center gap-2">
                    <div className="h-4 w-4 rounded bg-border" />
                    <div className="h-3 w-32 rounded bg-border" />
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-4 w-4 rounded bg-border" />
                    <div className="h-3 w-28 rounded bg-border" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="flex h-64 flex-col items-center justify-center rounded-xl border border-red-500/30 bg-red-500/10 text-red-500 gap-3 p-6 text-center">
            <ServerCrash className="h-10 w-10" />
            <h3 className="text-lg font-bold">{errorTitle}</h3>
            <p className="text-sm opacity-80 max-w-md whitespace-pre-line">{error}</p>
          </div>
        )}

        {/* Dashboard Content */}
        {status && (
          <div className="space-y-6 animate-in fade-in duration-500">
            
            {/* Overall Status Banner */}
            <div className={`flex items-center gap-4 rounded-xl border p-6 ${
              status.status === "healthy" 
                ? "border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400" 
                : status.status === "degraded"
                ? "border-yellow-500/30 bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
                : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400"
            }`}>
              {getStatusIcon(status.status)}
              <div>
                <h2 className="text-xl font-bold capitalize">{status.status}</h2>
                <p className="text-sm opacity-80">
                  {status.status === "healthy" 
                    ? "All systems operating normally."
                    : status.status === "degraded"
                    ? "Some components are experiencing issues."
                    : "Critical system failure detected."}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              
              {/* Components */}
              <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
                <h3 className="mb-4 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">Component Health</h3>
                <div className="space-y-4">
                  
                  <div className="flex items-center justify-between border-b border-border pb-3">
                    <div className="flex items-center gap-3">
                      <Activity className="h-4 w-4 text-muted" />
                      <span className="font-medium text-foreground">API Server</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm capitalize ${getStatusColor(status.components.api)}`}>{status.components.api}</span>
                      {getStatusIcon(status.components.api)}
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-b border-border pb-3">
                    <div className="flex items-center gap-3">
                      <Database className="h-4 w-4 text-muted" />
                      <span className="font-medium text-foreground">Database</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm capitalize ${getStatusColor(status.components.database)}`}>{status.components.database}</span>
                      {getStatusIcon(status.components.database)}
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-b border-border pb-3">
                    <div className="flex items-center gap-3">
                      <Activity className="h-4 w-4 text-muted" />
                      <span className="font-medium text-foreground">Queue</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex flex-col items-end">
                        <span className={`text-sm capitalize ${getStatusColor(status.components.queue)}`}>{status.components.queue}</span>
                        {status.health_checks.redis?.latency_ms !== undefined && (
                           <span className="text-xs text-muted">{status.health_checks.redis.latency_ms}ms</span>
                        )}
                      </div>
                      {getStatusIcon(status.components.queue)}
                    </div>
                  </div>

                  <div className="flex items-center justify-between border-b border-border pb-3">
                    <div className="flex items-center gap-3">
                      <BrainCircuit className="h-4 w-4 text-muted" />
                      <span className="font-medium text-foreground">Embeddings</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex flex-col items-end">
                        <span className={`text-sm capitalize ${getStatusColor(status.components.embeddings)}`}>{status.components.embeddings}</span>
                        {status.health_checks.embedding?.latency_ms !== undefined && (
                           <span className="text-xs text-muted">{status.health_checks.embedding.latency_ms}ms</span>
                        )}
                      </div>
                      {getStatusIcon(status.components.embeddings)}
                    </div>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <BrainCircuit className="h-4 w-4 text-muted" />
                      <span className="font-medium text-foreground">LLM Service</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex flex-col items-end">
                        <span className={`text-sm capitalize ${getStatusColor(status.components.llm)}`}>{status.components.llm}</span>
                        {status.health_checks.llm?.latency_ms !== undefined && (
                           <span className="text-xs text-muted">{status.health_checks.llm.latency_ms}ms</span>
                        )}
                      </div>
                      {getStatusIcon(status.components.llm)}
                    </div>
                  </div>

                </div>
              </div>

              {/* Metrics */}
              <div className="rounded-xl border border-border bg-surface p-6 shadow-sm">
                <h3 className="mb-4 font-mono text-[0.78rem] uppercase tracking-[2px] text-accent">System Metrics</h3>
                
                <div className="grid grid-cols-2 gap-4">
                  <div className="rounded-lg border border-border bg-background p-4">
                    <span className="text-xs text-muted uppercase tracking-wider block mb-1">Queue Depth</span>
                    <span className="text-2xl font-bold text-foreground">{status.metrics.document_queue}</span>
                  </div>
                  
                  <div className="rounded-lg border border-border bg-background p-4">
                    <span className="text-xs text-muted uppercase tracking-wider block mb-1">Active Workers</span>
                    <span className="text-2xl font-bold text-foreground">{status.metrics.workers_active}</span>
                  </div>

                  <div className="rounded-lg border border-border bg-background p-4">
                    <span className="text-xs text-muted uppercase tracking-wider block mb-1">Memory Usage</span>
                    <div className="flex items-end gap-2">
                      <span className="text-2xl font-bold text-foreground">{status.metrics.memory_usage}%</span>
                      <div className="h-6 w-full bg-surface rounded-sm overflow-hidden mb-1 flex-1 border border-border">
                        <div 
                          className={`h-full ${status.metrics.memory_usage > 85 ? 'bg-red-500' : status.metrics.memory_usage > 70 ? 'bg-yellow-500' : 'bg-accent'}`} 
                          style={{ width: `${status.metrics.memory_usage}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="rounded-lg border border-border bg-background p-4">
                    <span className="text-xs text-muted uppercase tracking-wider block mb-1">Docs Indexed</span>
                    <span className="text-2xl font-bold text-foreground">
                      {status.metrics.documents_indexed !== null ? status.metrics.documents_indexed.toLocaleString() : "—"}
                    </span>
                  </div>
                </div>

                <div className="mt-6 border-t border-border pt-4">
                  <div className="flex items-center gap-2 text-sm text-muted">
                    <Clock className="h-4 w-4" />
                    <span>Uptime: {status.uptime}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted mt-2">
                    <Cpu className="h-4 w-4" />
                    <span>Version: {status.version}</span>
                  </div>
                </div>

              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}