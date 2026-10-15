"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  FileCheck2,
  Info,
  LayoutGrid,
  LoaderCircle,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  OwnerCard,
  ReviewResults,
  StationCard,
} from "@/components/review-results";
import type { Policies, ReviewResponse } from "@/lib/review-types";
import { useAuth } from "@/components/auth-provider";

type View =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "error"; message: string }
  | { kind: "done"; report: ReviewResponse };
type HistoryEntry = { code: string; time: string };

export function ReviewWorkspace() {
  const { user, apiFetch, logout } = useAuth();
  const [code, setCode] = useState("");
  const [view, setView] = useState<View>({ kind: "idle" });
  const [policy, setPolicy] = useState<Policies | null>(null);
  const [policyError, setPolicyError] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const pending = useRef<AbortController | null>(null);
  const runId = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/policy", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("检查规则加载失败，请确认服务已启动后刷新页面。");
        setPolicy(await response.json());
      })
      .catch((error) => {
        if (!controller.signal.aborted) setPolicyError(error.message);
      });
    return () => {
      controller.abort();
      pending.current?.abort();
      runId.current += 1;
    };
  }, [apiFetch]);

  async function runReview(input: string) {
    const projectCode = input.trim();
    if (!projectCode) return;
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const current = ++runId.current;
    const timeout = setTimeout(() => controller.abort(), 120_000);
    setView({ kind: "pending" });
    try {
      const response = await apiFetch("/api/project-reviews", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ projectCode }),
        signal: controller.signal,
      });
      const report = await response.json();
      if (current !== runId.current) return;
      if (!response.ok && !["not_found", "ambiguous"].includes(report.status))
        throw new Error(report.message || "台账查询失败，请重试。");
      if (
        !["clear", "duplicate", "review", "not_found", "ambiguous"].includes(
          report.status,
        )
      )
        throw new Error("服务返回结果无效，本次检查未完成。");
      setView({ kind: "done", report });
      setHistory((entries) =>
        [
          {
            code: report.target?.code ?? projectCode,
            time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
          },
          ...entries,
        ].slice(0, 8),
      );
    } catch (error) {
      if (current !== runId.current) return;
      setView({
        kind: "error",
        message: controller.signal.aborted
          ? "查询超时，本次检查未完成，请稍后重试。"
          : error instanceof Error
            ? error.message
            : "本次检查未完成，请稍后重试。",
      });
    } finally {
      clearTimeout(timeout);
      if (current === runId.current) pending.current = null;
    }
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runReview(code);
  }

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col border-r bg-[#edf1e9] px-6 py-8 lg:flex">
        <a href="/" className="flex items-center gap-3">
          <span className="flex h-11 w-10 shrink-0 items-center justify-center rounded bg-primary font-serif text-2xl text-white">
            序
          </span>
          <span className="text-base font-semibold">
            流程自动审批
            <small className="mt-1 block text-[8px] tracking-[.2em] text-muted-foreground">
              FLOW APPROVAL
            </small>
          </span>
        </a>
        <p className="mt-14 mb-4 px-3 text-xs text-muted-foreground">
          审批阶段
        </p>
        <div
          aria-current="page"
          className="flex items-center gap-3 rounded-md bg-accent p-3 text-sm font-semibold text-primary"
        >
          <LayoutGrid className="size-4" />
          立项<span className="ml-auto text-xs opacity-60">01</span>
        </div>
        <div className="mt-auto mb-12 flex gap-3 px-3 font-serif text-xl leading-9 text-[#627566]">
          <span className="mt-4 size-1.5 shrink-0 rounded-full bg-primary" />
          <p>
            让每一次立项
            <br />
            都有清晰依据。
          </p>
        </div>
        <div className="flex items-center gap-3 border-t pt-6 text-xs">
          <span className="flex size-8 items-center justify-center rounded-full bg-accent">
            台
          </span>
          <p>
            项目合同台账
            <small className="mt-1 block text-[10px] text-muted-foreground">
              本地只读查询
            </small>
          </p>
        </div>
      </aside>
      <div className="lg:ml-56">
        <header className="flex h-16 items-center justify-between border-b px-5 text-xs sm:h-[75px] sm:px-11">
          <strong className="hidden font-medium sm:block">流程自动审批</strong>
          <div className="mr-2 flex min-w-0 items-center gap-2 sm:ml-auto sm:gap-3">
            <span className="max-w-20 truncate sm:max-w-32" title={user.username}>
              {user.display_name || user.username || "已登录用户"}
            </span>
            {user.department_name && <span className="hidden text-muted-foreground sm:inline">{user.department_name}</span>}
            <Button variant="ghost" size="sm" onClick={logout}>退出登录</Button>
          </div>
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="sm">
                <Info className="size-4" />
                查看检查规则
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
              <DialogHeader>
                <p className="mb-1 text-[10px] tracking-[.2em] text-muted-foreground">
                  MATCHING POLICY
                </p>
                <DialogTitle className="font-serif text-2xl">
                  检查规则说明
                </DialogTitle>
                <DialogDescription>
                  按产品类别选择规则。资料缺失、类别不明确或检查失败时提示待核实。
                </DialogDescription>
              </DialogHeader>
              {policy ? (
                <div className="space-y-6 text-sm leading-7">
                  {policy.policies.map((rule) => (
                    <section key={rule.id}>
                      <h3 className="mb-2 font-semibold">{rule.name}</h3>
                      <p className="text-muted-foreground">
                        {rule.description}
                      </p>
                      <dl className="mt-3">
                        {rule.fields.map((f) => (
                          <div
                            key={f.key}
                            className="flex justify-between gap-4 border-b py-2 text-xs"
                          >
                            <dt>{f.label}</dt>
                            <dd className="text-muted-foreground">
                              {f.key === rule.lookup?.key
                                ? rule.checkFields.some((c) => c.key === f.key)
                                  ? "同名检索并比对"
                                  : "同名检索"
                                : "一致性比对"}
                            </dd>
                          </div>
                        ))}
                      </dl>
                    </section>
                  ))}
                  <ol className="list-decimal pl-5 text-xs text-muted-foreground">
                    <li>按项目编号读取资料，依据类别字段自动选择规则。</li>
                    <li>资料或类别缺失、类别冲突时提示待核实。</li>
                    <li>文本按原值、枚举按编号比较；容量按数值比较。</li>
                    <li>三类年份缺失时提示待核实，不从名称补取。</li>
                    <li>不按项目状态过滤；按记录 ID 排除当前项目。</li>
                  </ol>
                  <section>
                    <h3 className="font-semibold">一二类业主校验</h3>
                    <p>{policy.ownerPolicy.description}</p>
                    <p className="text-muted-foreground">
                      {policy.ownerPolicy.lookup}
                    </p>
                    <p className="text-muted-foreground">
                      {policy.ownerPolicy.fallback}
                    </p>
                  </section>
                  <section>
                    <h3 className="font-semibold">场站类型分类校验</h3>
                    <p>{policy.stationPolicy.description}</p>
                    <p className="text-muted-foreground">
                      {policy.stationPolicy.lookup}
                    </p>
                    <p className="text-muted-foreground">
                      {policy.stationPolicy.scope}
                    </p>
                  </section>
                </div>
              ) : (
                <p role="status" className="text-sm text-muted-foreground">
                  {policyError || "正在加载检查规则…"}
                </p>
              )}
            </DialogContent>
          </Dialog>
        </header>
        <main className="mx-auto max-w-[1140px] px-5 pt-9 pb-6 sm:px-11 sm:pt-12">
          <div className="mb-8 flex flex-wrap items-center justify-between gap-5">
            <div>
              <p className="text-[10px] tracking-[.2em] text-muted-foreground">
                FLOW APPROVAL / INITIATION
              </p>
              <h1 className="mt-3 mb-4 font-serif text-3xl font-semibold tracking-wide sm:text-4xl">
                流程自动审批
              </h1>
              <p className="text-sm leading-7 text-muted-foreground">
                输入项目编号，自动识别产品类别，核对对应立项资料。
              </p>
            </div>
            <span className="flex items-center gap-2 rounded border bg-[#eff4e8] px-3 py-2 text-xs text-[#667953]">
              <span className="size-1.5 rounded-full bg-[#567c48]" />
              台账查询
            </span>
          </div>
          <Card className="gap-5 shadow-none">
            <CardHeader>
              <CardTitle className="flex items-center gap-3">
                <span className="border-r pr-3 font-serif font-normal text-muted-foreground">
                  01
                </span>
                选择要检查的项目
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={submit}>
                <Label
                  htmlFor="project-code"
                  className="mb-3 block text-xs text-muted-foreground"
                >
                  项目编号
                </Label>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <div className="relative flex-1">
                    <Search className="pointer-events-none absolute top-4 left-4 size-4 text-muted-foreground" />
                    <Input
                      id="project-code"
                      name="code"
                      value={code}
                      onChange={(e) => {
                        e.target.setCustomValidity("");
                        setCode(e.target.value);
                      }}
                      onInvalid={(e) => {
                        if (!e.currentTarget.value.trim())
                          e.currentTarget.setCustomValidity("请输入项目编号");
                      }}
                      required
                      pattern=".*\S.*"
                      maxLength={255}
                      autoComplete="off"
                      placeholder="请输入项目编号"
                      aria-describedby="input-hint"
                      className="h-12 bg-background pl-11"
                    />
                  </div>
                  <Button
                    type="submit"
                    disabled={view.kind === "pending"}
                    className="h-12 min-w-36 gap-6"
                  >
                    {view.kind === "pending" ? "正在检查" : "开始检查"}
                    {view.kind === "pending" ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <ArrowRight className="size-4" />
                    )}
                  </Button>
                </div>
                <p
                  id="input-hint"
                  className="mt-3 text-xs leading-6 text-muted-foreground"
                >
                  校验场站类型分类；一二类按电厂及五项资料查重并校验业主，三类按六项资料查重。
                </p>
              </form>
            </CardContent>
          </Card>
          <div
            id="result"
            aria-live="polite"
            aria-busy={view.kind === "pending"}
            className="my-7 space-y-5"
          >
            {view.kind === "idle" && (
              <section className="py-10 text-center">
                <FileCheck2
                  strokeWidth={1}
                  className="mx-auto mb-7 size-16 text-[#718b66]"
                />
                <p className="text-[10px] tracking-[.2em] text-muted-foreground">
                  READY WHEN YOU ARE
                </p>
                <h2 className="mt-3 mb-4 font-serif text-xl">
                  按产品类别，逐项核对
                </h2>
                <p className="text-xs leading-7 text-muted-foreground">
                  一二类：核对电厂、地区、产品子类和容量，并校验业主。
                  <br />
                  三类：核对电网、电力公司、部门、年份、类别和产品。
                  <br />
                  当前项目自身不计入查重结果。
                </p>
                <div className="mt-6 flex justify-center divide-x text-[10px] text-muted-foreground">
                  {["01 输入编号", "02 识别类别", "03 逐项比对"].map((item) => (
                    <span key={item} className="px-4">
                      {item}
                    </span>
                  ))}
                </div>
              </section>
            )}
            {view.kind === "pending" && (
              <>
                <OwnerCard owner={{ status: "pending" }} />
                <StationCard review={{ status: "pending" }} />
                <p className="flex items-center justify-center gap-3 py-8 text-sm text-muted-foreground">
                  <LoaderCircle className="size-5 animate-spin" />
                  正在读取项目资料，执行各项校验…
                </p>
              </>
            )}
            {view.kind === "error" && (
              <>
                <OwnerCard />
                <StationCard />
                <Card
                  className="border-[#e9dfc7] bg-[#faf4e6] shadow-none"
                  role="alert"
                >
                  <CardHeader>
                    <CardTitle>本次检查未完成</CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm leading-7">
                    {view.message}
                  </CardContent>
                </Card>
              </>
            )}
            {view.kind === "done" && <ReviewResults report={view.report} />}
          </div>
          {history.length > 0 && (
            <section className="my-8" aria-label="本次访问的检查记录">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold">本次访问的检查记录</h2>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setHistory([])}
                >
                  清空记录
                </Button>
              </div>
              {history.map((entry, i) => (
                <div
                  key={`${entry.code}-${i}`}
                  className="flex items-center justify-between border-b py-2"
                >
                  <Button
                    variant="link"
                    className="px-0"
                    onClick={() => {
                      setCode(entry.code);
                      void runReview(entry.code);
                    }}
                  >
                    {entry.code}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {entry.time}
                  </span>
                </div>
              ))}
            </section>
          )}
          <footer className="flex flex-col justify-between gap-2 border-t pt-5 text-[10px] leading-6 text-muted-foreground sm:flex-row">
            <span>流程自动审批</span>
            <span>数据源：项目合同台账 · 查重、业主与场站类型校验</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
