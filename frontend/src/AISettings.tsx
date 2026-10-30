import { useEffect, useState } from "react";
import {
  KeyRound,
  LoaderCircle,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { Data, Button, Badge } from "./ui";

export default function AISettings({
  api,
  onChanged,
}: {
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
  onChanged: () => Promise<void>;
}) {
  const [base, setBase] = useState("https://api.xiaomimimo.com/v1"),
    [model, setModel] = useState("mimo-v2.6-pro"),
    [key, setKey] = useState(""),
    [hasKey, setHasKey] = useState(false),
    [busy, setBusy] = useState(false),
    [ready, setReady] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  useEffect(() => {
    api("/ai/settings")
      .then((s: Data) => {
        if (s.provider === "mimo") {
          setBase(s.base_url);
          setModel(s.model);
        }
        setHasKey(s.has_key);
        setReady(true);
      })
      .catch((e) => setError(e.message));
  }, []);
  return (
    <div className="ai-settings">
      <div className="ai-provider">
        <KeyRound size={25} />
        <div>
          <h2>小米 MiMo</h2>
          <p>课程通知文本与截图理解 · 结构化 JSON</p>
        </div>
        <Badge status={hasKey ? "feasible" : "pending"}>
          {hasKey ? "已配置 Key" : "尚未连接"}
        </Badge>
      </div>
      <p className="ai-instructions">
        Key 仅发送至本机后端并保存在本机
        .env，不写入浏览器存储或业务数据库。测试会向你填写的 MiMo
        官方地址发送一条合成文本，可能消耗少量额度；截图测试需另行上传图片。
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          setNotice("");
          try {
            const s = await api("/ai/test-and-save", "POST", {
              base_url: base,
              model,
              api_key: key,
            });
            setKey("");
            setHasKey(true);
            setNotice(s.notice);
            await onChanged();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          API Base URL
          <input
            type="url"
            required
            value={base}
            onChange={(e) => setBase(e.target.value)}
            autoComplete="off"
          />
          <small>
            普通按量 Key 使用默认地址。Token Plan
            请填写控制台提供的专属地址与对应 Key。
          </small>
        </label>
        <label>
          视觉模型名称
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            required
            list="mimo-models"
          />
          <datalist id="mimo-models">
            <option value="mimo-v2.6-pro" />
            <option value="mimo-v2.6-flash" />
          </datalist>
          <small>默认 mimo-v2.6-pro；请确保你的账户有调用权限。</small>
        </label>
        <label>
          API Key
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder={
              hasKey
                ? "留空可继续使用原地址的已保存 Key"
                : "粘贴 MiMo 控制台签发的 Key"
            }
            autoComplete="new-password"
            spellCheck={false}
          />
        </label>
        <div className="form-footer">
          <Button type="submit" disabled={busy || !ready}>
            {busy ? (
              <LoaderCircle className="spin" size={16} />
            ) : (
              <CheckCircle2 size={16} />
            )}{" "}
            {busy ? "正在测试连接…" : "测试连接并保存"}
          </Button>
          <Button
            secondary
            disabled={busy || !ready}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api("/ai/demo", "POST");
                setKey("");
                setHasKey(false);
                setNotice("已移除本地 Key，切回明确标注的规则演示。");
                await onChanged();
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            移除 Key，使用演示模式
          </Button>
        </div>
      </form>
      {error && (
        <div className="alert error" role="alert">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}
      {notice && (
        <div className="alert success" role="status">
          <CheckCircle2 size={16} />
          {notice}
        </div>
      )}
      <div className="ai-links">
        <a
          href="https://platform.xiaomimimo.com/"
          target="_blank"
          rel="noreferrer"
        >
          打开 MiMo 控制台 ↗
        </a>
        <a
          href="https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/multimodal-understanding/image-understanding"
          target="_blank"
          rel="noreferrer"
        >
          官方图片理解文档 ↗
        </a>
      </div>
    </div>
  );
}
