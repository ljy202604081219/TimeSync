import { useEffect, useState } from "react";
import {
  Upload,
  Plus,
  Trash2,
  Check,
  LoaderCircle,
  AlertTriangle,
} from "lucide-react";
import { Button, Badge, Data, range } from "./ui";

export default function TimetableImport({
  api,
  me,
  initialWeek,
  onSaved,
}: {
  api: (
    path: string,
    method?: string,
    body?: unknown,
    form?: boolean,
  ) => Promise<any>;
  me: Data;
  initialWeek?: string;
  onSaved: () => Promise<void>;
}) {
  const initial = new Date((initialWeek || me.window_start.slice(0, 10)) + "T12:00:00Z");
  initial.setUTCDate(initial.getUTCDate() - ((initial.getUTCDay() + 6) % 7));
  const [week, setWeek] = useState(initial.toISOString().slice(0, 10));
  const [file, setFile] = useState<File | null>(null),
    [imageURL, setImageURL] = useState(""),
    [notes, setNotes] = useState(""),
    [schoolProfile, setSchoolProfile] = useState<Data | null>(null),
    [useSchoolSchedule, setUseSchoolSchedule] = useState(true),
    [courses, setCourses] = useState<Data[]>([]),
    [mode, setMode] = useState("manual"),
    [label, setLabel] = useState(""),
    [ambiguities, setAmbiguities] = useState<string[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [preview, setPreview] = useState<Data | null>(null),
    [confirmed, setConfirmed] = useState(false),
    [saved, setSaved] = useState<Data | null>(null);
  useEffect(() => {
    let active = true;
    api("/timetable/profile").then((value) => {
      if (active) setSchoolProfile(value);
    }).catch((e) => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!file) {
      setImageURL("");
      return;
    }
    const url = URL.createObjectURL(file);
    setImageURL(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  function changed() {
    setPreview(null);
    setConfirmed(false);
    setSaved(null);
  }
  function edit(id: string, name: string, value: unknown) {
    changed();
    setCourses((prev) =>
      prev.map((row) => {
        if (row.id !== id) return row;
        const edited = { ...row, [name]: value };
        if (name === "start_time" || name === "end_time") edited.time_basis = "";
        if (useSchoolSchedule && name === "start_time" && value === "19:00" && !row.end_time) {
          edited.end_time = schoolProfile?.evening_end || "21:35";
          edited.time_basis = "湖大晚课默认结束21:35，可手动修改。";
        }
        return edited;
      }),
    );
  }
  function add() {
    changed();
    setCourses((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        selected: true,
        title: "",
        weekday: "",
        start_time: "",
        end_time: "",
        evidence: "",
        ambiguities: [],
      },
    ]);
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function payload() {
    return {
      week_start: week,
      source: mode,
      courses: courses
        .filter((r) => r.selected)
        .map((r) => ({
          title: r.title,
          weekday: r.weekday === "" ? null : Number(r.weekday),
          start_time: r.start_time,
          end_time: r.end_time,
          evidence: r.evidence || "",
        })),
    };
  }
  return (
    <div className="timetable-import">
      <div className="alert warning">
        <AlertTriangle size={17} />
        截图会发送给你配置的视觉模型。已提供湖大默认节次作息；单双周和指定周次须人工核对，本次只导入选定的一周。
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!file) return;
          changed();
          perform(async () => {
            const form = new FormData();
            form.append("image", file);
            form.append("notes", notes);
            form.append("use_school_schedule", String(useSchoolSchedule));
            const result = await api("/timetable/extract", "POST", form, true);
            setMode(result.mode === "live" ? "ai" : "demo");
            setLabel(result.label);
            setAmbiguities(result.data.ambiguities);
            setCourses(
              result.data.courses.map((r: Data) => ({
                ...r,
                id: crypto.randomUUID(),
                selected: true,
                title: r.title || "",
                weekday: r.weekday ?? "",
                start_time: r.start_time || "",
                end_time: r.end_time || "",
              })),
            );
          });
        }}
      >
        <label className="confirm-check">
          <input type="checkbox" checked={useSchoolSchedule} disabled={busy}
            onChange={(e) => { setUseSchoolSchedule(e.target.checked); changed(); }} />
          使用湖大默认作息；19:00开始的课程默认到21:35
        </label>
        {schoolProfile && (
          <details className="course-evidence">
            <summary>{schoolProfile.label} · 查看11节时间</summary>
            {schoolProfile.periods.map((period: Data) => (
              <p key={period.number}>第{period.number}节：{period.start}–{period.end}</p>
            ))}
            <p>{schoolProfile.notice}</p>
          </details>
        )}
        <label className="upload-zone">
          <Upload size={25} />
          <b>上传整周课表截图</b>
          <small>PNG / JPEG / WebP，最大 6 MB；请保留星期列与时间轴</small>
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            required
            disabled={busy}
            onChange={(e) => {
              changed();
              setCourses([]);
              setLabel("");
              setAmbiguities([]);
              setFile(e.target.files?.[0] || null);
            }}
          />
        </label>
        {imageURL && (
          <img
            className="timetable-image"
            src={imageURL}
            alt="待识别的课表截图"
          />
        )}
        <label>
          课表补充说明（可选；其他学校请取消默认作息）
          <textarea
            rows={3}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              changed();
            }}
            placeholder="例如：本截图为第9周，仅导入单周课程。湖大节次时间已默认提供，无需重复填写。"
          />
        </label>
        <Button type="submit" disabled={busy || !file}>
          {busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <Upload size={16} />
          )}
          识别课表截图
        </Button>
      </form>
      {label && (
        <div className="timetable-label">
          <Badge status={mode === "demo" ? "pending" : "feasible"}>
            {label}
          </Badge>
        </div>
      )}
      {ambiguities.length > 0 && (
        <div className="ambiguities">
          <b>需要你核对</b>
          {ambiguities.map((a, i) => (
            <p key={i}>{a}</p>
          ))}
        </div>
      )}
      <form
        className="timetable-confirm"
        onSubmit={(e) => {
          e.preventDefault();
          perform(async () => {
            const submitted = payload();
            const result = await api("/timetable/preview", "POST", submitted);
            setPreview({ ...result, input_key: JSON.stringify(submitted) });
            setConfirmed(false);
            setSaved(null);
          });
        }}
      >
        <div className="form-row">
          <label>
            导入目标周的周一
            <input
              type="date"
              value={week}
              required
              onChange={(e) => {
                setWeek(e.target.value);
                changed();
              }}
            />
          </label>
          <Button
            secondary
            onClick={add}
            disabled={busy || courses.length >= 70}
          >
            <Plus size={15} />
            手动添加课程
          </Button>
        </div>
        <p className="ai-instructions">
          只勾选目标周确实上课的记录。未识别清楚的字段保持空白，必须补全或取消勾选；导入只追加固定课程，不覆盖已有课表。
        </p>
        {courses.map((r, i) => (
          <section key={r.id} className="course-review">
            <div className="course-review-head">
              <label>
                <input
                  type="checkbox"
                  checked={r.selected}
                  disabled={busy}
                  onChange={(e) => edit(r.id, "selected", e.target.checked)}
                />
                第 {i + 1} 条课程
              </label>
              <button
                className="icon-button"
                type="button"
                disabled={busy}
                aria-label={`删除第${i + 1}条课程`}
                onClick={() => {
                  changed();
                  setCourses(courses.filter((c) => c.id !== r.id));
                }}
              >
                <Trash2 size={15} />
              </button>
            </div>
            <div className="course-fields">
              <label>
                课程名称
                <input
                  value={r.title}
                  disabled={!r.selected || busy}
                  required
                  onChange={(e) => edit(r.id, "title", e.target.value)}
                />
              </label>
              <label>
                星期
                <select
                  value={r.weekday}
                  disabled={!r.selected || busy}
                  required
                  onChange={(e) => edit(r.id, "weekday", e.target.value)}
                >
                  <option value="">待确认</option>
                  {["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map(
                    (d, n) => (
                      <option key={d} value={n}>
                        {d}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label>
                开始
                <input
                  type="time"
                  value={r.start_time}
                  disabled={!r.selected || busy}
                  required
                  onChange={(e) => edit(r.id, "start_time", e.target.value)}
                />
              </label>
              <label>
                结束
                <input
                  type="time"
                  value={r.end_time}
                  disabled={!r.selected || busy}
                  required
                  onChange={(e) => edit(r.id, "end_time", e.target.value)}
                />
              </label>
            </div>
            <div className="course-evidence">
              <b>原文证据</b>
              <p>{r.evidence || "手动添加 / 无可核对证据，请自行确认。"}</p>
              {r.time_basis && <p className="course-ambiguity">{r.time_basis}</p>}
              {r.ambiguities?.map((a: string, n: number) => (
                <p className="course-ambiguity" key={n}>
                  {a}
                </p>
              ))}
            </div>
          </section>
        ))}
        <Button
          type="submit"
          disabled={busy || !courses.some((r) => r.selected)}
        >
          检查并预览导入
        </Button>
      </form>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {preview && preview.input_key === JSON.stringify(payload()) && (
        <section className="course-preview">
          <h3>
            将新增 {preview.create_count} 条，跳过 {preview.skip_count}{" "}
            条重复课程
          </h3>
          {preview.courses.map((r: Data, i: number) => (
            <div className="course-preview-row" key={i}>
              <b>{r.title}</b>
              <span>{range(r.start, r.end)}</span>
              <small>
                {r.duplicate
                  ? "已存在，将跳过"
                  : r.conflicts.length
                    ? "与 " + r.conflicts.join("、") + " 重叠"
                    : "新增固定课程"}
              </small>
              {!r.duplicate && r.task_conflicts?.length > 0 && (
                <small>
                  将影响原任务：{r.task_conflicts.join("、")}，请重新排程。
                </small>
              )}
            </div>
          ))}
          {preview.warnings.map((w: string) => (
            <p className="ai-instructions" key={w}>
              {w}
            </p>
          ))}
          <label className="confirm-check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              disabled={!!saved || busy}
            />
            我已核对目标周、节次时间、单双周/停课规则及重叠提示，确认导入这些课程。
          </label>
          <Button
            disabled={
              busy || !confirmed || !!saved || preview.create_count === 0
            }
            onClick={() =>
              perform(async () => {
                const result = await api("/timetable/import", "POST", {
                  ...payload(),
                  confirmed: true,
                  expected_snapshot: preview.expected_snapshot,
                });
                setSaved(result);
                await onSaved();
              })
            }
          >
            <Check size={16} />
            {saved ? "已导入日历" : "确认导入个人日历"}
          </Button>
          {saved && (
            <div className="alert success" role="status">
              已新增 {saved.created} 条课程，跳过 {saved.skipped}{" "}
              条重复记录。请重新生成个人计划，使任务避开新课表。
            </div>
          )}
        </section>
      )}
    </div>
  );
}
