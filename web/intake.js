"use strict";
const $ = id => document.getElementById(id);
const fields = ["project_name", "project_type", "development_environment", "target_environment", "toolchain",
  "build_dir", "architecture", "cross_compile", "build_command", "build_env", "editable_paths",
  "blocked_paths", "change_notes", "code_guidelines"];
const kinds = {freeform:"자유 요청", sdd:"SDD", jira:"Jira", srs:"SRS", verification:"검증 피드백"};
const cliLabels = {waiting_for_agent:"전송 대기", cli_queued:"Claude 전송 대기", cli_running:"Claude 응답 중", cli_complete:"Claude 응답 완료", cli_failed:"Claude 호출 실패", cli_interrupted:"실행 중단 · 확인 필요"};
const state = {token:"", workspace:"", config:null, base:"", files:[], scan:null,
  sample:"", tasks:[], selected:"", shown:40, busy:false, retry:null, detailSequence:0, cliInstalled:false, pollTimer:null, dispatchKeys:{}};
function formConfig() { return Object.fromEntries(fields.map(key => [key, $(key).value.trim()])); }
function dirty() { return state.base !== JSON.stringify(formConfig()) || $("workspace").value.trim() !== state.workspace; }
function notice(text, error=false) { $("message").textContent=text; $("message").classList.toggle("error", error); $("message").hidden=false; }
async function api(url, body) {
  const options = body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json", "X-AX-Token":state.token}, body:JSON.stringify(body)};
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || "요청을 처리하지 못했습니다.");
  return data;
}
function ready() {
  const configured = Boolean(state.config?.revision);
  const changed = Boolean(state.workspace) && dirty();
  $("profileStatus").textContent = changed ? "저장하지 않은 변경" : configured ? "환경 저장됨" : "설정 필요";
  $("unsaved").textContent = changed ? "변경 사항을 저장한 뒤 요청을 접수하세요." : configured ? "현재 환경이 저장되어 있습니다." : "설정을 저장해 주세요.";
  $("environmentFields").disabled = !state.workspace || state.busy;
  for (const id of ["connect", "sample", "refreshQueue"]) $(id).disabled = state.busy;
  $("goRequest").disabled = state.busy || !configured || changed;
  const blocked = state.busy || !configured || changed || !state.files.length || state.scan?.truncated;
  $("saveRequest").disabled = blocked;
  $("submitRequest").disabled = blocked || !state.cliInstalled;
}
async function action(callback) {
  if (state.busy) return;
  state.busy=true; ready();
  try { await callback(); } catch (error) { notice(error.message, true); }
  finally { state.busy=false; ready(); const button=$("dispatchRequest"); if(button) {const task=state.tasks.find(item=>item.id===state.selected);button.disabled=!state.cliInstalled || !task || task.configuration_stale || ["cli_queued","cli_running"].includes(task.status) || button.dataset.exhausted==="true";} }
}
function page(name) {
  if (name === "request" && (!state.config?.revision || dirty())) {
    notice("개발 환경을 먼저 저장하세요. 경로를 변경했다면 다시 연결해 주세요.", true);
    name="environment";
  }
  for (const [view, nav] of [["environment", "navEnvironment"], ["request", "navRequest"], ["queue", "navQueue"]]) {
    $(view+"View").hidden = view !== name;
    if (view === name) $(nav).setAttribute("aria-current", "page"); else $(nav).removeAttribute("aria-current");
  }
  if (name === "queue") loadQueue().catch(error => notice(error.message, true));
  if (name === "request") renderProfile();
}
function renderFiles() {
  const query = $("fileSearch").value.trim().toLowerCase();
  const matches = state.files.filter(file => file.path.toLowerCase().includes(query));
  $("fileCount").textContent = `${state.files.length}개`;
  $("fileList").replaceChildren(...matches.slice(0, state.shown).map(file => {
    const li = document.createElement("li"); li.textContent = file.path; return li;
  }));
  if (!matches.length) { const li=document.createElement("li"); li.textContent="일치하는 파일이 없습니다."; $("fileList").append(li); }
  $("moreFiles").hidden = state.shown >= matches.length;
  const scan = state.scan;
  $("scanStatus").textContent = scan ? `${scan.editable_files}개 파일 · ${scan.truncated ? "탐색 제한: " + scan.limit_reason : "탐색 완료"}${scan.missing_paths.length ? " · 없는/제외된 경로: " + scan.missing_paths.join(", ") : ""}` : "환경을 저장하면 허용 파일 목록이 표시됩니다.";
}
function pairs(container, entries) {
  const dl=document.createElement("dl"); dl.className="detail";
  for (const [label,value] of entries) {const dt=document.createElement("dt"), dd=document.createElement("dd"); dt.textContent=label; dd.textContent=value || "미지정"; dl.append(dt,dd);}
  container.append(dl);
}
function renderProfile() {
  const root=$("activeProfile"); root.replaceChildren(); const c=state.config || {};
  pairs(root, [["프로젝트", c.project_name], ["Project Root",state.workspace], ["개발 환경",c.development_environment],
    ["대상 환경",c.target_environment], ["도구 버전",c.toolchain], ["빌드 명령",c.build_command],
    ["수정 허용 경로",c.editable_paths], ["제외 경로",c.blocked_paths], ["허용 파일",`${state.files.length}개`]]);
  if (state.scan?.truncated || !state.files.length) {const p=document.createElement("p"); p.className="stale"; p.textContent="수정 가능한 파일을 확인하고 탐색 제한을 해결한 뒤 요청을 접수하세요."; root.append(p);}
}
async function connect(path) {
  clearTimeout(state.pollTimer);
  const data=await api("/api/workspace", {path});
  state.workspace=data.path; state.config=data.config; state.files=data.files; state.scan=data.scan;
  $("workspace").value=data.path;
  for (const key of fields) $(key).value=data.config[key] || "";
  state.base=JSON.stringify(formConfig()); state.shown=40; state.selected="";
  state.detailSequence++;
  $("requestDetail").replaceChildren();
  const empty=document.createElement("p"); empty.className="empty"; empty.textContent="요청을 선택하면 전달 내용을 확인할 수 있습니다."; $("requestDetail").append(empty);
  $("connectedPath").textContent=`연결됨: ${data.path} · 브랜치: ${data.branch || "없음"}`;
  renderFiles(); renderProfile(); await loadQueue(); ready();
}
async function loadQueue() {
  const workspace=state.workspace;
  const data=await api("/api/requests");
  if (workspace !== state.workspace) return;
  state.tasks=data.tasks.filter(task => task.workspace === workspace);
  $("queueCount").textContent=state.tasks.length;
  renderQueue();
}
function renderQueue() {
  const root=$("requestList"); root.replaceChildren();
  const origin=$("originFilter").value;
  const tasks=state.tasks.filter(task => origin === "all" || task.origin === origin);
  if (!tasks.length) {const p=document.createElement("p"); p.className="empty"; p.textContent=state.workspace ? "접수된 요청이 없습니다. 요청 작성에서 첫 작업을 접수하세요." : "개발 환경에서 프로젝트를 연결하세요."; root.append(p); return;}
  for (const task of tasks) {
    const button=document.createElement("button"); button.type="button"; button.className="request-item";
    button.setAttribute("aria-pressed", String(state.selected === task.id));
    const badge=document.createElement("span"); badge.className="badge"; badge.textContent=task.configuration_stale ? "환경 변경 · 재접수 필요" : (cliLabels[task.status] || task.status);
    const title=document.createElement("strong"); title.textContent=task.instruction.slice(0,100);
    const meta=document.createElement("small"); meta.textContent=`${kinds[task.source_kind]} · ${task.origin === "agent" ? task.source_agent : "직접 요청"} · ${new Date(task.created_at).toLocaleString("ko-KR")}`;
    button.append(badge,title,meta); button.addEventListener("click", () => openDetail(task.id).catch(error => notice(error.message,true))); root.append(button);
  }
}
async function openDetail(id) {
  clearTimeout(state.pollTimer);
  state.selected=id;
  const sequence=++state.detailSequence;
  const data=await api("/api/requests/"+encodeURIComponent(id));
  if (sequence !== state.detailSequence) return;
  const listed=state.tasks.find(item=>item.id===id);
  if (listed) Object.assign(listed,{status:data.task.status,configuration_stale:data.task.configuration_stale});
  renderQueue(); renderDetail(data.task);
  if (["cli_queued", "cli_running"].includes(data.task.status)) {
    state.pollTimer=setTimeout(() => {
      if (state.selected===id) openDetail(id).catch(error => notice("실행 상태 조회 실패: " + error.message + " · 새로고침으로 다시 확인하세요.",true));
    },1500);
  }
}
function renderDetail(task) {
  const root=$("requestDetail");
  const expanded=new Set(Array.from(root.querySelectorAll("details[open]")).map(item=>item.dataset.section));
  root.replaceChildren();
  const payload=task.payload, env=payload.environment;
  const heading=document.createElement("h3"); heading.textContent="개발 요청 · Claude Code 응답"; root.append(heading);
  const info=document.createElement("p"); info.className="notice"; info.textContent=cliLabels[task.status] || task.status; root.append(info);
  if (task.configuration_stale) {const warning=document.createElement("p"); warning.className="stale"; warning.textContent="접수 후 환경 설정이 변경되었습니다. 아래는 접수 당시 내용입니다. 현재 설정으로 다시 접수해야 향후 에이전트가 사용할 수 있습니다."; root.append(warning);}
  renderCliRun(root, task, expanded);
  pairs(root, [["요청 ID", task.id], ["요청 근거",kinds[task.source_kind]], ["출처", task.origin === "agent" ? task.source_agent : "직접 요청"],
    ["상위 실행 ID",task.upstream_run_id], ["참조 ID / 링크",task.source_ref], ["개발 요청",task.instruction], ["참고 본문", task.source_content],
    ["프로젝트",env.project_name], ["Project Root",payload.workspace], ["설정 버전",env.revision],
    ["개발 환경",env.development_environment], ["대상 환경",env.target_environment], ["도구 버전",env.toolchain],
    ["빌드 작업 폴더",env.build_dir], ["ARCH / CROSS_COMPILE",[env.architecture,env.cross_compile].filter(Boolean).join(" / ")],
    ["빌드 명령",env.build_command], ["빌드 환경변수",env.build_env], ["수정 허용 경로",env.editable_paths], ["수정 제외 경로",env.blocked_paths],
    ["개발 대상 설명",env.change_notes], ["코딩 규칙",env.code_guidelines]]);
  const files=document.createElement("details"), summary=document.createElement("summary"), list=document.createElement("ul");
  summary.textContent=`접수 당시 수정 가능 파일 ${payload.scope.editable_files.length}개`;
  list.className="file-list";
  for (const file of payload.scope.editable_files) {const li=document.createElement("li");li.textContent=file.path;list.append(li);}
  files.dataset.section="files"; files.open=expanded.has("files"); files.append(summary,list); root.append(files);
  const json=document.createElement("details"), label=document.createElement("summary"), pre=document.createElement("pre");
  json.dataset.section="json"; json.open=expanded.has("json"); label.textContent="접수 당시 전달 데이터 JSON 보기"; pre.className="json"; pre.textContent=JSON.stringify(payload,null,2); json.append(label,pre); root.append(json);
  const actions=document.createElement("div"); actions.className="detail-actions";
  const download=document.createElement("button");download.type="button";download.className="secondary";download.textContent="전달 JSON 다운로드";
  download.addEventListener("click", () => {
    const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)+"\n"],{type:"application/json"}));
    const a=document.createElement("a");a.href=url;a.download=`code-dev-${task.id}.json`;a.click();setTimeout(() => URL.revokeObjectURL(url),1000);
  });
  const reuse=document.createElement("button"); reuse.type="button"; reuse.className="secondary"; reuse.textContent="이 요청으로 다시 작성";
  reuse.addEventListener("click", () => {$("sourceKind").value=task.source_kind;$("sourceRef").value=task.source_ref;$("sourceContent").value=task.source_content;$("instruction").value=task.instruction;state.retry=null;page("request");});
  actions.append(download,reuse);root.append(actions);
}
function renderCliRun(root, task, expanded) {
  const runs=task.cli_runs || [], latest=runs.at(-1);
  const prompt=document.createElement("details"), summary=document.createElement("summary"), pre=document.createElement("pre");
  prompt.dataset.section="prompt"; prompt.open=expanded.has("prompt");
  summary.textContent=latest ? "실제 전송한 프롬프트" : "Claude CLI에 전달할 프롬프트";
  pre.className="json"; pre.textContent=latest?.prompt || task.cli_prompt_error || task.cli_prompt || "요청을 다시 열면 프롬프트를 확인할 수 있습니다.";
  prompt.append(summary,pre);root.append(prompt);
  if (latest) {
    const status=document.createElement("p");status.className="hint";status.textContent=`실행 ${runs.length}/5 · ${latest.id} · ${new Date(latest.updated_at).toLocaleString("ko-KR")}`;root.append(status);
    if (latest.error) {const error=document.createElement("p");error.className="stale";error.textContent=latest.error;root.append(error);}
    if (latest.response) {const response=document.createElement("pre");response.className="json cli-response";response.textContent=latest.response;root.append(response);}
    const log=document.createElement("details"), title=document.createElement("summary"), content=document.createElement("pre");
    log.dataset.section="log";log.open=expanded.has("log");title.textContent="CLI 실행 기록";content.className="json";
    content.textContent=(latest.events || []).map(event=>`${event.role}: ${event.text}`).join("\n\n");log.append(title,content);root.append(log);
    if (runs.length>1) {
      const history=document.createElement("details"), title=document.createElement("summary");history.dataset.section="history";history.open=expanded.has("history");title.textContent="이전 전송 결과";history.append(title);
      for (const run of runs.slice(0,-1)) {const item=document.createElement("pre");item.className="json";item.textContent=`${cliLabels[run.status]} · ${run.created_at}\n${run.response || run.error}`;history.append(item);}root.append(history);
    }
  }
  const send=document.createElement("button");send.type="button";send.id="dispatchRequest";
  send.textContent=latest ? "Claude Code에 다시 전달" : "Claude Code로 전달";
  send.dataset.exhausted=String(runs.length>=5);
  send.disabled=task.configuration_stale || ["cli_queued","cli_running"].includes(task.status) || runs.length>=5 || state.busy || !state.cliInstalled;
  send.onclick=() => action(async()=>{send.disabled=true;await dispatchRequest(task.id);});root.append(send);
  const note=document.createElement("p");note.className="hint";note.textContent="요청·환경·파일 경로가 설정된 AI 서비스로 전송됩니다. 파일 읽기·수정 및 빌드는 실행하지 않습니다.";root.append(note);
}
async function dispatchRequest(id) {
  if (!state.dispatchKeys[id]) state.dispatchKeys[id]=requestKey();
  await api("/api/requests/dispatch",{id,idempotency_key:state.dispatchKeys[id]});
  delete state.dispatchKeys[id];
  await loadQueue();await openDetail(id);
  notice("Claude Code CLI 전송을 시작했습니다. 응답 완료 또는 실패 상태를 확인하세요.");
}
async function refreshCli(status) {
  const info=status || await api("/api/claude/status");state.cliInstalled=Boolean(info.installed);
  $("cliStatus").textContent=info.installed ? "Claude Code CLI 감지됨" : "Claude Code CLI 설치 필요";
  $("cliNote").textContent=info.note;ready();
}
function requestKey() { return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2,"0")).join(""); }
async function initialize() {
  $("refreshCli").onclick=()=>action(async()=>{await refreshCli();if(state.selected)await openDetail(state.selected);});
  $("navEnvironment").onclick=() => page("environment"); $("navRequest").onclick=() => page("request"); $("navQueue").onclick=() => page("queue");
  $("goRequest").onclick=() => page("request"); $("editEnvironment").onclick=() => page("environment");
  const mayConnect=path => {
    if (state.workspace && dirty() && !window.confirm("저장하지 않은 환경 설정을 버리고 프로젝트를 다시 연결할까요?")) return;
    action(async () => { await connect(path); notice("프로젝트를 연결했습니다."); });
  };
  $("connect").onclick=() => mayConnect($("workspace").value.trim()); $("sample").onclick=() => mayConnect(state.sample);
  $("workspace").addEventListener("input",ready); $("environmentForm").addEventListener("input",ready);
  $("fileSearch").oninput=() => {state.shown=40;renderFiles();}; $("moreFiles").onclick=() => {state.shown+=40;renderFiles();};
  $("originFilter").onchange=renderQueue; $("refreshQueue").onclick=() => action(async () => {await loadQueue();if(state.selected) await openDetail(state.selected);});
  $("example").onclick=() => {$("instruction").value="IFPMIC 충전 입력 전류 설정 함수에서 음수 및 최대 허용값 초과 입력을 차단해줘. 정상 범위의 기존 동작은 유지하고 오류 반환 경로를 설명해줘.";};
  $("environmentForm").onsubmit=event => {event.preventDefault();action(async () => {
    if ($("workspace").value.trim() !== state.workspace) throw new Error("변경한 경로를 먼저 연결하세요.");
    await api("/api/config/save", {workspace:state.workspace,config:formConfig(),expected_revision:state.config?.revision || ""});
    await connect(state.workspace);notice("개발 환경을 저장했습니다. 요청 작성으로 이동할 수 있습니다.");
  });};
  $("requestForm").onsubmit=event => {event.preventDefault();const sendNow=event.submitter?.id !== "saveRequest";action(async () => {
    if (!state.config?.revision || dirty()) throw new Error("개발 환경을 저장한 뒤 요청하세요.");
    const body={workspace:state.workspace,expected_revision:state.config.revision,source_kind:$("sourceKind").value,
      source_ref:$("sourceRef").value,source_content:$("sourceContent").value,instruction:$("instruction").value};
    const fingerprint=JSON.stringify(body);
    if (state.retry?.fingerprint !== fingerprint) state.retry={fingerprint,key:requestKey()};
    body.idempotency_key=state.retry.key;
    const data=await api("/api/requests",body);
    state.selected=data.task.id;await loadQueue();page("queue");await openDetail(data.task.id);
    if (sendNow) {
      // A form retry must not send an already-started request a second time.
      const existing=(await api("/api/requests/"+data.task.id)).task;
      if (!(existing.cli_runs || []).length) await dispatchRequest(data.task.id);
    } else notice("요청을 저장했습니다. 상세 화면에서 Claude Code로 전달할 수 있습니다.");
  });};
  window.addEventListener("beforeunload", event => {if (state.workspace && dirty()) {event.preventDefault();event.returnValue="";}});
  await action(async () => {
    const data=await api("/api/bootstrap");state.token=data.token;state.sample=data.sample_path;await refreshCli(data.claude_cli);
    $("agentIntakeStatus").textContent=data.agent_intake_enabled ? "외부 요청 접수 활성화 · X-AX-Agent-Token 인증 필요" : "외부 요청 접수 비활성화 · AX_AGENT_TOKEN 설정 후 서버 재시작";
    $("legacyLink").hidden=!data.legacy_claude_enabled;
    if(data.last_workspace) await connect(data.last_workspace);
    else {$("workspace").value=state.sample;notice("실제 프로젝트 경로를 연결하거나 샘플로 시작하세요.");}
  });
}
document.addEventListener("DOMContentLoaded",initialize);
