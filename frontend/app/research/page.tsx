"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { createResearchTask, fetchResearchTask, fetchResearchTasks } from "@/lib/api/research";
import type { ResearchTaskDetail, ResearchTaskSummary } from "@/types/research";

const STAGES = ["drafting", "researching", "writing", "reviewing", "done", "archived"];

export default function ResearchPage() {
  const [tasks, setTasks] = useState<ResearchTaskSummary[]>([]);
  const [active, setActive] = useState<ResearchTaskDetail | null>(null);
  const [topic, setTopic] = useState("");

  const loadTasks = useCallback(async () => setTasks(await fetchResearchTasks()), []);
  useEffect(() => { void loadTasks(); }, [loadTasks]);

  // 轮询刷新当前任务状态（实时推送留待 Agent spec）。
  useEffect(() => {
    if (!active) return;
    const id = setInterval(async () => setActive(await fetchResearchTask(active.id)), 3000);
    return () => clearInterval(id);
  }, [active?.id]);

  async function handleCreate() {
    if (!topic.trim()) return;
    const created = await createResearchTask({ topic: topic.trim() });
    setTopic("");
    setActive(created);
    await loadTasks();
  }

  return (
    <main style={{ display: "flex", gap: 24, padding: 24 }}>
      <aside style={{ width: 260 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="研究主题" />
          <button onClick={handleCreate}>新建</button>
        </div>
        <ul>
          {tasks.map((t) => (
            <li key={t.id}>
              <button onClick={async () => setActive(await fetchResearchTask(t.id))}>
                {t.topic}（{t.status}）
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {active && (
        <section style={{ flex: 1 }}>
          <h2>{active.topic}</h2>
          <ProgressBar status={active.status} />
          <Section title="大纲">
            {active.outline.map((o) => (
              <div key={o.id}><strong>{o.title}</strong>: {o.points.join("；")}</div>
            ))}
          </Section>
          <Section title="事实（可溯源）">
            {active.facts.map((f) => (
              <div key={f.id}>{f.content} <small>[{f.provenance.source ?? f.provenance.agent}]</small></div>
            ))}
          </Section>
          <Section title="数据点">{json(active.data_points)}</Section>
          <Section title="图表">{json(active.charts)}</Section>
          <Section title="草稿">{json(active.drafts)}</Section>
          <Section title="评审反馈">{json(active.reviews)}</Section>
        </section>
      )}
    </main>
  );
}

function ProgressBar({ status }: { status: string }) {
  const idx = STAGES.indexOf(status);
  return (
    <div style={{ display: "flex", gap: 8, margin: "12px 0" }}>
      {STAGES.map((s, i) => (
        <span key={s} style={{ fontWeight: i === idx ? 700 : 400, opacity: i <= idx ? 1 : 0.4 }}>{s}</span>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginTop: 16 }}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function json(data: unknown) {
  return <pre style={{ fontSize: 12 }}>{JSON.stringify(data, null, 2)}</pre>;
}
