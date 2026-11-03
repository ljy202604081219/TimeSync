import { useState } from "react";
import {
  AlertTriangle,
  Check,
  Upload,
  WandSparkles,
  LoaderCircle,
  Plus,
  Trash2,
  RefreshCw,
  Layers3,
  MoveRight,
} from "lucide-react";
import {
  Data,
  Button,
  Badge,
  iso,
  range,
  md,
  hm,
  SolveResult,
  ScheduleList,
  Changes,
} from "./ui";

export function TaskForm({
  initial,
  tasks,
  extracted,
  busy,
  onSave,
}: {
  initial?: Data;
  tasks: Data[];
  extracted?: Data;
  busy: boolean;
  onSave: (data: Data) => Promise<void>;
}) {
  const [confirmed, setConfirmed] = useState(!extracted),
    [deadline, setDeadline] = useState(
      (initial?.deadline || extracted?.data.deadline || "").slice(0, 16),
    );
  return (
    <form
      className="task-form"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        onSave({
          title: f.get("title"),
          deadline: iso(deadline),
          duration_minutes: Number(f.get("duration")),
          priority: Number(f.get("priority")),
          dependencies: f.getAll("dependencies").map(Number),
          requirements: f.get("requirements"),
          evidence: f.get("evidence"),
          source:
            initial?.source ||
            (extracted
              ? extracted.mode === "demo"
                ? "demo"
                : "ai"
              : "manual"),
        });
      }}
    >
      <label>
        任务名称
        <input
          name="title"
          required
          maxLength={160}
          defaultValue={initial?.title || extracted?.data.title || ""}
          placeholder="例如：机器学习实验报告"
        />
      </label>
      <div className="form-row">
        <label>
          截止时间（上海时间）
          <input
            type="datetime-local"
            value={deadline}
            required
            onChange={(e) => setDeadline(e.target.value)}
          />
        </label>
        <label>
          预计耗时（分钟，连续安排）
          <input
            name="duration"
            type="number"
            min={15}
            max={1440}
            step={15}
            required
            defaultValue={initial?.duration_minutes || 60}
          />
        </label>
      </div>
      <label>
        优先级
        <select
          name="priority"
          defaultValue={initial?.priority || extracted?.data.priority || 2}
        >
          <option value={1}>低</option>
          <option value={2}>中</option>
          <option value={3}>高</option>
        </select>
        <small>原文未说明的优先级由你选择，默认中等。</small>
      </label>
      <label>
        提交要求
        <textarea
          name="requirements"
          rows={2}
          defaultValue={
            initial?.requirements || extracted?.data.requirements || ""
          }
        />
      </label>
      <label>
        原文证据
        <textarea
          name="evidence"
          rows={2}
          defaultValue={initial?.evidence || extracted?.data.evidence || ""}
          placeholder="手动任务可留空"
        />
      </label>
      <fieldset>
        <legend>前置任务（需先完成）</legend>
        <div className="dependencies">
          {tasks
            .filter((t) => t.id !== initial?.id)
            .map((t) => (
              <label key={t.id}>
                <input
                  type="checkbox"
                  name="dependencies"
                  value={t.id}
                  defaultChecked={initial?.dependencies.includes(t.id)}
                />
                {t.title}
              </label>
            ))}
        </div>
      </fieldset>
      {extracted && (
        <label className="confirm-check">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          我已核对任务、完整截止时间、证据和歧义，确认保存。
        </label>
      )}
      <div className="form-footer">
        <span>保存后请在智能排程中更新计划。</span>
        <Button type="submit" disabled={busy || !confirmed}>
          <Check size={16} />
          确认保存任务
        </Button>
      </div>
    </form>
  );
}
export function ExtractPanel({
  tasks,
  busy,
  request,
  onSave,
}: {
  tasks: Data[];
  busy: boolean;
  request: (data: FormData) => Promise<Data>;
  onSave: (data: Data) => Promise<void>;
}) {
  const [result, setResult] = useState<Data | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  return (
    <div className="extract-panel">
      <div className="alert warning">
        <AlertTriangle size={16} />
        没有 API Key 时仅进行文本规则演示；截图需要配置视觉模型才能识别。
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          const file = f.get("image") as File;
          if (file && !file.size) f.delete("image");
          setLoading(true);
          setError("");
          setResult(null);
          try {
            setResult(await request(f));
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setLoading(false);
          }
        }}
      >
        <label>
          课程通知文本
          <textarea
            name="text"
            rows={4}
            defaultValue={
              "机器学习 · 实验二报告\n请于2026年11月5日18:00前提交实验报告，要求 PDF 格式，并附源代码。"
            }
          />
        </label>
        <label className="upload-zone">
          <Upload size={23} />
          <b>上传课程通知截图</b>
          <small>PNG / JPEG / WebP · 最大 6 MB</small>
          <input
            type="file"
            name="image"
            accept="image/png,image/jpeg,image/webp"
          />
        </label>
        <Button type="submit" disabled={loading}>
          {loading ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <WandSparkles size={16} />
          )}{" "}
          {loading ? "正在提取…" : "提取并校验信息"}
        </Button>
      </form>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {result && (
        <div className="extracted">
          <div className="section-heading">
            <h2>核对识别结果</h2>
            <Badge status={result.mode === "demo" ? "pending" : "feasible"}>
              {result.label}
            </Badge>
          </div>
          <div className="ambiguities">
            <b>
              <AlertTriangle size={16} />
              需要你确认
            </b>
            {result.data.ambiguities.map((a: string) => (
              <p key={a}>{a}</p>
            ))}
          </div>
          <TaskForm
            key={JSON.stringify(result)}
            tasks={tasks}
            extracted={result}
            busy={busy}
            onSave={onSave}
          />
          <details>
            <summary>查看结构化 JSON</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
export function RepairPanel({
  result,
  busy,
  state,
  onPreview,
  onCommit,
}: {
  result: Data | null;
  busy: boolean;
  state: Data;
  onPreview: (data: Data) => Promise<void>;
  onCommit: (data: Data) => Promise<void>;
}) {
  const [event, setEvent] = useState({
      title: "临时增加实验",
      start: "2026-11-04T14:00",
      end: "2026-11-04T16:00",
    }),
    [submitted, setSubmitted] = useState("");
  const payload = {
    title: event.title,
    start: iso(event.start),
    end: iso(event.end),
  };
  const valid = result && JSON.stringify(payload) === submitted;
  return (
    <>
      <div className="repair-intro">
        <div className="repair-orbit">
          <RefreshCw size={30} />
        </div>
        <div>
          <span className="eyebrow">LESS DISRUPTION, MORE FOCUS</span>
          <h2>只调整必须调整的部分。</h2>
          <p>保留原计划，移动冲突任务。每一次变化，都有记录、有原因。</p>
        </div>
      </div>
      <section className="card">
        <div className="section-heading">
          <h2>
            <span className="step-label">01</span>新增突发事件
          </h2>
          <Badge>先预览，后确认</Badge>
        </div>
        <form
          className="repair-form"
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(JSON.stringify(payload));
            onPreview(payload);
          }}
        >
          <label>
            事件名称
            <input
              value={event.title}
              required
              onChange={(e) => setEvent({ ...event, title: e.target.value })}
            />
          </label>
          <label>
            开始时间
            <input
              type="datetime-local"
              value={event.start}
              required
              onChange={(e) => setEvent({ ...event, start: e.target.value })}
            />
          </label>
          <label>
            结束时间
            <input
              type="datetime-local"
              value={event.end}
              required
              onChange={(e) => setEvent({ ...event, end: e.target.value })}
            />
          </label>
          <Button disabled={busy} type="submit">
            <WandSparkles size={16} />
            预览修复方案
          </Button>
        </form>
      </section>
      {valid && result ? (
        <>
          <SolveResult result={result} />
          {result.meeting_conflicts?.map((c: Data) => (
            <div className="alert warning" key={c.id}>
              <AlertTriangle size={17} />
              {c.title}：{c.reason}
            </div>
          ))}
          <section className="card">
            <div className="section-heading">
              <div>
                <h2>
                  <span className="step-label">02</span>修复前后对比
                </h2>
                <p>
                  基于版本 #{result.expected_plan_id} · {result.changes.length}{" "}
                  项变化
                </p>
              </div>
              <Badge>
                {result.id ? `已保存版本 #${result.id}` : "预览 · 尚未写入"}
              </Badge>
            </div>
            <Changes changes={result.changes} />
            <details className="full-plan-details"><summary>查看完整修复前后计划</summary><div className="compare-columns"><div><h3>修复前</h3><ScheduleList items={result.before}/></div><div><h3>修复后</h3><ScheduleList items={result.schedule}/></div></div></details>
            <div className="confirmation-footer">
              <p>
                {["optimal", "feasible"].includes(result.status)
                  ? "确认后同时保存突发事件与新计划，旧版本可追溯。"
                  : "确认后仅记录事件与诊断；旧计划标记待修复。"}
              </p>
              <Button
                disabled={busy || !!result.id}
                onClick={() =>
                  onCommit({
                    ...payload,
                    expected_plan_id: result.expected_plan_id,
                    expected_snapshot: result.expected_snapshot,
                  })
                }
              >
                <Check size={16} />
                {result.id
                  ? "已确认保存"
                  : ["optimal", "feasible"].includes(result.status)
                    ? "确认采用修复方案"
                    : "确认记录事件与冲突"}
              </Button>
            </div>
          </section>
        </>
      ) : (
        <section className="card repair-placeholder">
          <span className="step-label">02</span>
          <h2>改变什么，保留什么，清楚再决定。</h2>
          <p>预览后将展示每项变动的原时间、新时间和调整原因。</p>
          <div className="placeholder-bars">
            <i />
            <MoveRight />
            <i />
          </div>
        </section>
      )}
      <div className="quiet-note">
        <Layers3 size={16} />
        已有 {state.versions.length} 个计划版本。不可行诊断同样可追溯。
      </div>
    </>
  );
}
export function Settings({
  state,
  me,
  busy,
  onAdd,
  onDelete,
  onWindow,
  onImport,
}: {
  state: Data;
  me: Data;
  busy: boolean;
  onAdd: (kind: string, data: Data) => Promise<void>;
  onDelete: (kind: string, id: number) => Promise<void>;
  onWindow: (data: Data) => Promise<void>;
  onImport: () => void;
}) {
  const [kind, setKind] = useState("busy");
  return (
    <div className="settings-panel">
      <Button secondary onClick={onImport} disabled={busy}>
        <Upload size={16} />
        上传课表截图并识别
      </Button>
      <div className="alert warning">
        可用时段是硬边界。修改后请重新排程；每周重复时段须在同一天内。
      </div>
      <form
        className="window-form"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          onWindow({
            start: iso(f.get("start") as string),
            end: iso(f.get("end") as string),
          });
        }}
      >
        <h3>排程窗口（最多 14 天）</h3>
        <div className="form-row">
          <label>
            开始
            <input
              name="start"
              type="datetime-local"
              required
              defaultValue={me.window_start.slice(0, 16)}
            />
          </label>
          <label>
            结束
            <input
              name="end"
              type="datetime-local"
              required
              defaultValue={me.window_end.slice(0, 16)}
            />
          </label>
          <Button secondary type="submit" disabled={busy}>
            保存窗口
          </Button>
        </div>
      </form>
      <h3>添加时间约束</h3>
      <form
        className="constraint-form"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          onAdd(kind, {
            start: iso(f.get("start") as string),
            end: iso(f.get("end") as string),
            weekday: f.get("weekday") === "" ? null : Number(f.get("weekday")),
            kind: f.get("kind"),
            ...(kind === "busy" ? { title: f.get("title") } : {}),
          });
        }}
      >
        <div className="form-row">
          <label>
            约束类型
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="busy">课程 / 不可用</option>
              <option value="availability">可用 / 不太方便</option>
            </select>
          </label>
          <label>
            分类
            <select key={kind} name="kind">
              {(kind === "busy"
                ? [
                    ["course", "固定课程"],
                    ["unavailable", "不可用"],
                  ]
                : [
                    ["available", "可用时间"],
                    ["uncomfortable", "不太方便（软偏好）"],
                  ]
              ).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>
        {kind === "busy" && (
          <label>
            名称
            <input name="title" required placeholder="例如：高等数学" />
          </label>
        )}
        <div className="form-row">
          <label>
            开始
            <input
              name="start"
              type="datetime-local"
              required
              defaultValue="2026-11-02T08:00"
            />
          </label>
          <label>
            结束
            <input
              name="end"
              type="datetime-local"
              required
              defaultValue="2026-11-02T10:00"
            />
          </label>
          <label>
            重复
            <select name="weekday">
              <option value="">仅该次</option>
              {["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map(
                (d, i) => (
                  <option value={i} key={d}>
                    每{d}
                  </option>
                ),
              )}
            </select>
          </label>
        </div>
        <Button secondary type="submit" disabled={busy}>
          <Plus size={15} />
          添加约束
        </Button>
      </form>
      <div className="constraint-lists">
        {(["busy", "availability"] as const).map((type) => (
          <div key={type}>
            <h3>
              {type === "busy" ? "固定课程与不可用时段" : "可用时段与偏好"}
            </h3>
            <div className="constraint-list">
              {state[type].map((c: Data) => (
                <div key={c.id}>
                  <div>
                    <b>
                      {c.title ||
                        (c.kind === "available" ? "可用" : "不太方便")}
                    </b>
                    <small>
                      {c.weekday === null
                        ? md(c.start)
                        : [
                            "每周一",
                            "每周二",
                            "每周三",
                            "每周四",
                            "每周五",
                            "每周六",
                            "每周日",
                          ][c.weekday]}{" "}
                      {hm(c.start)}–{hm(c.end)}
                    </small>
                  </div>
                  {c.kind !== "disruption" && (
                    <button
                      className="icon-button"
                      aria-label="删除约束"
                      disabled={busy}
                      onClick={() => onDelete(type, c.id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
