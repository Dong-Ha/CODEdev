"use strict";

const state = {
  token: null,
  workspace: null,
  files: [],
  scan: null,
  previewFile: "",
  proposal: null,
  activeTab: "diff",
  busy: false,
  configured: false,
  config: null,
  configBase: "",
  page: "code",
  configFile: "",
  requestMode: "human",
  handoffs: [],
  selectedHandoff: "",
  agentIntakeEnabled: false,
  activeRunId: "",
  displayedRunId: "",
  lastRun: null,
  lastEventSeq: 0,
};
const $ = (id) => document.getElementById(id);
const EDITABLE_FILES_PAGE_SIZE = 40;
const editableBrowserState = { code: { shown: EDITABLE_FILES_PAGE_SIZE }, env: { shown: EDITABLE_FILES_PAGE_SIZE } };

const SAMPLE_PROMPT = "IFPMIC 충전 입력 전류 설정 함수에서 음수 및 최대 허용값 초과 입력을 차단하고, 정상 범위의 기존 동작을 유지해줘.";
const PROFILE_FIELDS = {
  project_name: "envProjectName", project_type: "envProjectType", build_dir: "envBuildDir",
  architecture: "envArchitecture", cross_compile: "envCrossCompile", build_command: "envBuildCommand",
  build_env: "envBuildEnv", editable_paths: "envEditablePaths", blocked_paths: "envBlockedPaths",
  change_notes: "envChangeNotes", code_guidelines: "envCodeGuidelines",
};

function showPage(page, quiet = false) {
  if (page === "code" && !state.configured) {
    if (!quiet) toast("개발 환경 설정을 먼저 저장해 주세요.", "error");
    page = "settings";
  }
  state.page = page;
  $("codeDevView").classList.toggle("hidden", page !== "code");
  $("settingsView").classList.toggle("hidden", page !== "settings");
  for (const [id, active] of [["navCodeDev", page === "code"],["navEnvironment",page === "settings"]]) {
    $(id).classList.toggle("active", active);
  }
  $("currentPageName").textContent = page === "settings" ? "개발 환경" : "Code-Dev";
  window.scrollTo({top: 0, behavior: "instant"});
}

const SOURCE_LABELS = {
  freeform: "자유 요청", srs: "SRS", sdd: "SDD", jira: "Jira", verification: "검증 피드백",
};
const HANDOFF_LABELS = {
  queued: "대기", generating: "생성 중", review: "검토 필요", no_change: "변경 없음", needs_clarification: "추가 설명 필요",
  failed: "재시도 필요", applied: "반영 완료", rejected: "반려", undone: "되돌림",
};

function setRequestMode(mode) {
  state.requestMode = mode;
  const human = mode === "human";
  $("modeHuman").classList.toggle("selected", human);
  $("modeAgent").classList.toggle("selected", !human);
  $("modeHuman").setAttribute("aria-pressed", String(human));
  $("modeAgent").setAttribute("aria-pressed", String(!human));
  $("humanComposer").classList.toggle("hidden", !human);
  $("agentInbox").classList.toggle("hidden", human);
  $("taskPanelTitle").textContent = human ? "직접 개발 요청" : "에이전트 수신함";
  $("taskPanelSubtitle").textContent = human ? "SRS · SDD · Jira · 자유 요청" : "SDD 인계 · 검증 피드백";
  if (!human) loadInbox();
  if (!state.proposal && state.activeTab === "diff") renderPreview();
}

function updateReferenceFields() {
  const kind = $("requestKind").value;
  $("referenceFields").classList.toggle("hidden", kind === "freeform");
  $("requestRef").placeholder = kind === "jira" ? "예: PMIC-123 또는 Jira URL" : "문서 ID / 추적용 URL (선택)";
  $("referenceHint").textContent = kind === "jira"
    ? "Jira URL은 자동 조회하지 않습니다. 이슈 본문과 수용 조건을 아래에 붙여넣으세요."
    : "문서 ID는 추적용입니다. SRS/SDD 원문 또는 필요한 절을 아래에 붙여넣으세요.";
}

function incomingForWorkspace() {
  return state.handoffs.filter(item => item.workspace === state.workspace);
}

async function loadInbox() {
  const root = $("inboxList");
  try {
    const response = await request("/api/inbox");
    state.handoffs = response.tasks;
    const list = incomingForWorkspace();
    $("inboxCount").textContent = String(list.filter(t => ["queued", "failed", "review", "no_change"].includes(t.status)).length);
    root.replaceChildren();
    if (!list.length) {
      const empty = document.createElement("div"); empty.className = "inbox-empty";
      empty.textContent = "이 프로젝트에 전달된 작업이 없습니다. 상위 에이전트가 작업을 보내면 여기에 표시됩니다.";
      root.appendChild(empty);
      $("inboxDetails").classList.add("hidden");
      return;
    }
    for (const task of list) {
      const button = document.createElement("button"); button.type = "button";
      button.className = `inbox-item ${task.id === state.selectedHandoff ? "selected" : ""}`;
      button.setAttribute("aria-pressed", String(task.id === state.selectedHandoff));
      const heading = document.createElement("span"); heading.className = "inbox-item-title";
      heading.textContent = `${SOURCE_LABELS[task.source_kind] || task.source_kind} · ${task.source_agent}`;
      const status = document.createElement("span"); status.className = `inbox-task-status ${task.status}`;
      status.textContent = HANDOFF_LABELS[task.status] || task.status;
      const desc = document.createElement("span"); desc.className = "inbox-item-summary";
      desc.textContent = task.instruction;
      button.append(heading, status, desc);
      button.addEventListener("click", () => { state.selectedHandoff = task.id; loadInbox(); });
      root.appendChild(button);
    }
    const current = list.find(t => t.id === state.selectedHandoff);
    if (current) renderIncoming(current);
    else { state.selectedHandoff = ""; $("inboxDetails").classList.add("hidden"); }
  } catch (error) {
    root.replaceChildren();
    const issue = document.createElement("div"); issue.className = "inbox-error";
    issue.textContent = `수신함을 불러올 수 없습니다: ${error.message}`;
    root.appendChild(issue);
  }
}

function renderIncoming(task) {
  $("inboxDetails").classList.remove("hidden");
  $("incomingTitle").textContent = `${SOURCE_LABELS[task.source_kind] || task.source_kind} · ${HANDOFF_LABELS[task.status] || task.status}`;
  $("incomingMeta").textContent = `${task.source_agent} · ${task.upstream_run_id || "상위 실행 ID 없음"}`;
  $("incomingInstruction").textContent = task.instruction;
  $("incomingTarget").textContent = task.target || "자동 선택 · 수정 허용 파일";
  $("incomingReference").textContent = task.source_ref || "참조 ID 없음";
  $("incomingSourceDetails").classList.toggle("hidden", !task.source_content);
  $("incomingSourceContent").textContent = task.source_content || "";
  $("incomingError").classList.toggle("hidden", !task.error);
  $("incomingError").textContent = task.error || "";
  const button = $("inboxAction");
  button.disabled = task.status === "generating";
  button.textContent = ["queued", "failed"].includes(task.status)
    ? task.status === "failed" ? "변경안 다시 생성" : "변경안 생성"
    : task.proposal_id ? (["no_change", "needs_clarification"].includes(task.status) ? "응답 결과 확인하기" : "변경안 검토하기") : "처리 중";
}

async function openIncoming() {
  if (state.busy) return;
  const task = state.handoffs.find(item => item.id === state.selectedHandoff);
  if (!task) return toast("Select an incoming task first.", "error");
  if (task.workspace !== state.workspace) return toast("Reconnect the task workspace.", "error");
  setBusy(true, "Claude Code is working...");
  $("inboxAction").disabled = true;
  try {
    let proposal;
    if (["queued", "failed"].includes(task.status)) {
      state.proposal = null;
      renderPreview(); renderReview();
      showSubmitting(task.instruction);
      const response = await request("/api/jobs/handoff", {id: task.id});
      showRun(response.job, true);
      const done = await monitorRun(response.job.id);
      if (!["complete", "no_change", "needs_clarification"].includes(done.status)) throw new Error(done.error || "Claude Code job failed");
      proposal = (await request("/api/proposal", {id: done.proposal_id})).proposal;
    } else if (task.proposal_id) {
      proposal = (await request("/api/proposal", {id: task.proposal_id})).proposal;
      if (proposal.job_id) await showSavedRun(proposal.job_id);
    } else throw new Error("This task is already running. Refresh the inbox.");
    state.proposal = proposal;
    changeTab("diff"); renderReview(); await loadHistory();
    toast(proposal.status === "needs_clarification" ? "Claude Code가 추가 설명을 요청했습니다." : proposal.status === "no_change" ? "Claude Code가 정상 응답했지만 코드 변경은 없습니다. 판단 근거를 확인하세요." :
      "Review the conversation, provenance and Diff before applying.", ["no_change", "needs_clarification"].includes(proposal.status) ? "info" : "success");
  } catch (error) {
    showRunError(error.message);
    toast(error.message, "error");
  } finally {
    setBusy(false);
    await loadInbox();
  }
}

function envFromForm() {
  const result = Object.fromEntries(["development_environment", "target_environment", "toolchain"]
    .map(key => [key, state.config?.[key] || ""]));
  for (const [key, elementId] of Object.entries(PROFILE_FIELDS)) result[key] = $(elementId).value.trim();
  return result;
}

function formatScanStatus(scan) {
  if (!scan) return "개발 환경을 연결하면 탐색 결과가 표시됩니다.";
  const explored = Number(scan.scanned_files || 0).toLocaleString("ko-KR");
  const editable = Number(scan.editable_files || 0).toLocaleString("ko-KR");
  let message = `탐색 후보 ${explored}개 · 수정 허용 ${editable}개`;
  if (scan.truncated) message += ` · 탐색 제한: ${scan.limit_reason || "허용 경로를 좁혀주세요."}`;
  else if (!scan.editable_files) message += " · 허용된 파일이 없습니다. Project Root와 경로 패턴을 확인하세요.";
  else message += " · 탐색 완료";
  if (Array.isArray(scan.missing_paths) && scan.missing_paths.length) {
    message += ` · 없는/제외된 경로: ${scan.missing_paths.slice(0, 2).join(", ")}`;
    if (scan.missing_paths.length > 2) message += ` 외 ${scan.missing_paths.length - 2}개`;
  }
  return message;
}

function scanNeedsAttention(scan) {
  return Boolean(scan && (scan.truncated || (!scan.editable_files) || (scan.missing_paths || []).length));
}

// The workspace API already returns the complete discovered allowlisted file
// manifest (up to the server's scan budget). Display paths, not source text.
function renderEditableFileBrowser(kind, stale = false) {
  const prefix = kind === "env" ? "env" : "code";
  const panel = $(`${prefix}EditablePanel`);
  const files = Array.isArray(state.files) ? state.files : [];
  const show = state.configured && files.length > 0 && !stale;
  panel.classList.toggle("hidden", !show);
  if (!show) return;

  $(`${prefix}EditableTotal`).textContent = `${files.length.toLocaleString("ko-KR")}개`;
  const search = $(`${prefix}EditableSearch`).value.trim().toLocaleLowerCase();
  const matches = files.filter(f => f.path.toLocaleLowerCase().includes(search))
    .sort((a, b) => a.path.localeCompare(b.path, "ko"));
  const shown = Math.min(editableBrowserState[kind].shown, matches.length);
  $(`${prefix}EditableMatches`).textContent = search
    ? `검색 결과 ${matches.length.toLocaleString("ko-KR")}개`
    : `${shown.toLocaleString("ko-KR")} / ${files.length.toLocaleString("ko-KR")}개 표시`;
  const list = $(`${prefix}EditableList`);
  list.replaceChildren();
  if (!matches.length) {
    const row = document.createElement("li");
    row.className = "editable-files-empty";
    row.textContent = "검색 결과가 없습니다. 다른 파일명이나 경로로 검색해 보세요.";
    list.appendChild(row);
  } else {
    const fragment = document.createDocumentFragment();
    for (const file of matches.slice(0, shown)) {
      const row = document.createElement("li");
      row.className = "editable-files-row";
      const path = document.createElement("code");
      path.textContent = file.path; // Never interpret repository filenames as HTML.
      path.title = file.path;
      const size = document.createElement("span");
      size.className = "editable-files-size";
      size.textContent = file.size >= 1024 ? `${(file.size / 1024).toFixed(1)} KB` : `${file.size} B`;
      if (file.size > 8 * 1024 * 1024) {
        size.textContent += " · 처리 한도 초과";
        size.title = "경로 규칙에는 매칭됩니다. 다만 현재 호스트의 코드 처리 상한인 8MB를 초과하여 변경안 생성은 지원하지 않습니다.";
      } else if (file.size > 64 * 1024) {
        size.textContent += " · 구간 수정";
        size.title = "64KB 초과: 목록에 포함되며, Claude Code에는 원본과 일치하는 구간 교체 방식으로 요청합니다.";
      }
      row.append(path, size);
      fragment.appendChild(row);
    }
    list.appendChild(fragment);
  }
  const more = $(`${prefix}EditableMore`);
  more.classList.toggle("hidden", shown >= matches.length);
  more.textContent = `다음 ${Math.min(EDITABLE_FILES_PAGE_SIZE, matches.length - shown)}개 보기`;
  $(`${prefix}EditableFooter`).textContent = search
    ? `${matches.length.toLocaleString("ko-KR")}개 중 ${shown.toLocaleString("ko-KR")}개 · 검색 결과만 표시`
    : `Project Root 기준 · 전체 ${files.length.toLocaleString("ko-KR")}개 중 ${shown.toLocaleString("ko-KR")}개 표시`;
  const warning = $(`${prefix}EditableWarning`);
  warning.classList.toggle("hidden", !state.scan?.truncated);
  warning.textContent = state.scan?.truncated
    ? `탐색 제한으로 일부 파일만 표시할 수 있습니다. ${state.scan.limit_reason || "수정 허용 경로를 좁혀 주세요."}` : "";
}

function resetEditableFileBrowsers() {
  for (const kind of ["code", "env"]) {
    editableBrowserState[kind].shown = EDITABLE_FILES_PAGE_SIZE;
    $(`${kind}EditableSearch`).value = "";
  }
}

function setupEditableFileBrowserEvents() {
  for (const kind of ["code", "env"]) {
    $(`${kind}EditableSearch`).addEventListener("input", () => {
      editableBrowserState[kind].shown = EDITABLE_FILES_PAGE_SIZE;
      renderEditableFileBrowser(kind);
    });
    $(`${kind}EditableMore`).addEventListener("click", () => {
      editableBrowserState[kind].shown += EDITABLE_FILES_PAGE_SIZE;
      renderEditableFileBrowser(kind);
    });
  }
}

function renderEnvironmentSummary() {
  const data = envFromForm();
  $("envSummaryName").textContent = data.project_name || "프로젝트명 미설정";
  $("envSummaryPath").textContent = $("envWorkspacePath").value.trim() || "Workspace 연결 필요";
  $("envSummaryType").textContent = data.project_type === "linux-kernel" ? "Linux Kernel Driver" : "Generic project";
  $("envSummaryBuildDir").textContent = data.build_dir || ".";
  $("envSummaryCommand").textContent = data.build_command || "명령어를 입력하세요.";
  $("envSummaryScope").textContent = data.editable_paths || "경로 패턴을 입력하세요.";
  const rootChanged = $("envWorkspacePath").value.trim() !== state.workspace;
  const scopeChanged = rootChanged || data.editable_paths !== (state.config?.editable_paths || "") ||
    data.blocked_paths !== (state.config?.blocked_paths || "");
  const dirty = JSON.stringify(data) !== state.configBase || rootChanged;
  $("envUnsaved").textContent = !state.configured ? "초기 환경 설정이 필요합니다" :
    dirty ? "변경사항 미저장 · 저장 후 적용" : "모든 설정 저장됨";
  $("envUnsaved").classList.toggle("unsaved", dirty || !state.configured);
  $("envSummaryConfig").textContent = !state.configured ? "아직 설정되지 않은 프로젝트" :
    dirty ? "현재 입력은 저장되지 않았습니다" : "저장된 프로젝트 프로필";
  $("envSummaryFiles").textContent = !state.configured || scopeChanged ? "저장 후 계산" :
    `${state.files.length}개 파일`;
  $("envScanStatus").textContent = !state.configured || scopeChanged
    ? "경로를 저장하면 Project Root 아래에서 허용 파일을 우선 탐색합니다."
    : formatScanStatus(state.scan);
  $("envScanStatus").classList.toggle("warning", state.configured && !scopeChanged && scanNeedsAttention(state.scan));
  renderEditableFileBrowser("env", scopeChanged);
}

function populateEnvironment(data) {
  const profile = data.config || {};
  state.configured = Boolean(data.configured);
  state.config = profile;
  $("envWorkspacePath").value = data.path;
  for (const [key, elementId] of Object.entries(PROFILE_FIELDS)) $(elementId).value = profile[key] || "";
  state.configBase = JSON.stringify(envFromForm());
  $("envSetupBadge").textContent = state.configured ? "CONFIGURED" : "INITIAL SETUP";
  $("envSetupBadge").classList.toggle("configured", state.configured);
  $("envIntroText").textContent = state.configured ?
    "빌드 환경과 수정 허용 경로를 변경할 수 있습니다. 저장하면 새 코드 생성 요청부터 변경된 설정이 적용됩니다." :
    "먼저 프로젝트의 빌드 명령어와 수정 허용 범위를 설정하세요. 저장 후 Code-Dev에서 변경안을 생성할 수 있습니다.";
  $("envUpdateStamp").textContent = state.configured ? `최근 저장 ${new Date(profile.updated_at).toLocaleString("ko-KR")}` : "초기 설정 전";
  $("navConfigStatus").textContent = state.configured ? "설정됨" : "설정 필요";
  $("activeEnvBadge").textContent = state.configured ? "CONFIGURED" : "SETUP REQUIRED";
  $("activeEnvBadge").classList.toggle("configured", state.configured);
  $("activeBuildCommand").textContent = state.configured ? profile.build_command : "개발 환경 설정을 먼저 저장하세요.";
  $("activeEditablePaths").textContent = state.configured ? profile.editable_paths.replace(/\n/g, " · ") : "—";
  $("activeChangeNotes").textContent = state.configured ? profile.change_notes || "미지정" : "—";
  $("envBackBtn").disabled = !state.configured;
  renderEnvironmentSummary();
}

function applyEnvironmentTemplate(kind) {
  if (state.configured && !window.confirm("템플릿 값으로 일부 입력을 교체하시겠습니까? 저장 전까지 실제 설정은 바뀌지 않습니다.")) return;
  if (kind === "kernel") {
    $("envProjectType").value = "linux-kernel";
    $("envBuildDir").value = ".";
    $("envArchitecture").value = "arm64";
    $("envCrossCompile").value = "aarch64-linux-gnu-";
    $("envBuildCommand").value = "make O=out ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image dtbs modules";
    $("envEditablePaths").value = "drivers/power/supply/**\ninclude/linux/power/**";
    $("envBlockedPaths").value = "**/*.key\n**/secrets/**\n**/.env";
    $("envChangeNotes").value = "IFPMIC Charger / Fuel Gauge 드라이버의 변경 함수와 영향 범위를 작업 요청에 명시";
    $("envCodeGuidelines").value = "기존 커널 스타일, 오류 경로 및 동시성 고려. 요청 범위 밖 수정 금지.";
  } else {
    $("envProjectType").value = "generic";
    $("envBuildDir").value = ".";
    $("envArchitecture").value = "";
    $("envCrossCompile").value = "";
    $("envBuildCommand").value = "";
    $("envEditablePaths").value = "";
    $("envBlockedPaths").value = "**/*.key\n**/secrets/**\n**/.env";
    $("envChangeNotes").value = "";
    $("envCodeGuidelines").value = "기존 스타일 유지, 관련 없는 파일 수정 금지";
  }
  renderEnvironmentSummary();
  toast(kind === "kernel" ? "IFPMIC 템플릿이 입력되었습니다. 빌드 레시피를 실제 환경에 맞게 수정하세요." :
    "일반 프로젝트 템플릿을 적용했습니다. 명령어와 수정 허용 경로를 입력하세요.");
}

async function saveEnvironment() {
  const root = $("envWorkspacePath").value.trim();
  if (!state.workspace || root !== state.workspace) return toast("프로젝트 경로를 먼저 연결해 주세요.", "error");
  const firstSetup = !state.configured;
  const btn = $("envSaveBtn");
  btn.disabled = true;
  try {
    const result = await request("/api/config/save", {
      workspace: state.workspace, config: envFromForm(),
      expected_revision: state.configured ? state.config.revision : null,
    });
    toast(`환경 설정 저장 완료 · 수정 허용 ${result.editable_files}개 파일` +
      (result.scan && result.scan.truncated ? " · 탐색 제한이 있으니 경로를 좁혀주세요." : ""),
      result.scan && result.scan.truncated ? "info" : "success");
    await connectWorkspace(root, !firstSetup);
    if (firstSetup) showPage("code", true);
  } catch (err) { toast(err.message, "error"); }
  finally { btn.disabled = false; }
}

async function request(route, body) {
  const options = body === undefined ? { method: "GET" } : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-AX-Token": state.token },
    body: JSON.stringify(body),
  };
  let response;
  try {
    response = await fetch(route, options);
  } catch (e) {
    throw new Error("로컬 서버 연결 실패: app.py가 실행 중인지 확인하세요.");
  }
  let data;
  try { data = await response.json(); } catch (e) { throw new Error("서버에서 올바른 JSON이 반환되지 않았습니다."); }
  if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}


const RUN_STATE_LABELS = {queued:"대기",running:"진행 중",complete:"검토 대기",no_change:"변경 없음",needs_clarification:"추가 설명 필요",failed:"실패"};
const CLI_STATE_LABELS = {not_started:"Claude Code 호출 전",running:"Claude Code 호출 중",succeeded:"Claude Code 호출 성공",failed:"Claude Code 호출 실패"};
const RUN_ROLE_LABELS = {user:"내 요청",assistant:"Claude Code 응답",system:"실행 기록",error:"오류"};

function toggleRunConsole(open) {
  $("runConsoleBody").classList.toggle("hidden", !open);
  $("runConsoleToggle").setAttribute("aria-expanded", String(open));
  $("runConsoleToggle").textContent = open ? "기록 접기" : "기록 보기";
}

function showSubmitting(prompt) {
  state.displayedRunId = "";
  state.lastEventSeq = 0;
  state.lastRun = null;
  $("runMessages").replaceChildren();
  $("runStatus").textContent = "전송 중";
  $("runStatus").className = "run-status queued";
  $("runCliStatus").className = "run-cli-status not_started";
  $("runCliStatus").textContent = CLI_STATE_LABELS.not_started;
  $("runTargetLabel").textContent = "대상 파일 확인 전";
  $("runSummary").textContent = "Sending task to local Code-Dev server...";
  $("runElapsed").textContent = "00:00";
  $("runIdLabel").textContent = "Awaiting job ID";
  const row = document.createElement("div"); row.className = "run-message user";
  const avatar = document.createElement("span"); avatar.className = "run-icon"; avatar.textContent = "U";
  const content = document.createElement("div"); content.className = "run-message-body";
  const head = document.createElement("div"); head.className = "run-message-head";
  const name = document.createElement("strong"); name.textContent = RUN_ROLE_LABELS.user; head.appendChild(name);
  const msg = document.createElement("p"); msg.textContent = prompt;
  content.append(head,msg); row.append(avatar,content); $("runMessages").appendChild(row);
  toggleRunConsole(true);
  $("runConsole").scrollIntoView({behavior:"smooth", block:"start"});
}

function showRunError(error) {
  $("runStatus").textContent = RUN_STATE_LABELS.failed;
  $("runStatus").className = "run-status failed";
  $("runSummary").textContent = error;
  toggleRunConsole(true);
}

function showRun(job, expand = false) {
  if (!job || !job.id) return;
  if (state.displayedRunId !== job.id) {
    state.displayedRunId = job.id;
    state.lastEventSeq = 0;
    $("runMessages").replaceChildren();
  }
  state.lastRun = job;
  $("runStatus").className = `run-status ${job.status}`;
  $("runStatus").textContent = RUN_STATE_LABELS[job.status] || job.status;
  const cli = job.cli_status || "not_started";
  $("runCliStatus").className = `run-cli-status ${cli}`;
  $("runCliStatus").textContent = CLI_STATE_LABELS[cli] || "Claude Code 상태 확인 중";
  $("runTargetLabel").textContent = job.target ? `관련 파일: ${job.target}` : "허용 경로에서 관련 파일 확인 중";
  const secs = Math.max(0, Math.floor((Date.now() - Date.parse(job.created_at)) / 1000)) || 0;
  $("runElapsed").textContent = `${String(Math.floor(secs/60)).padStart(2,"0")}:${String(secs%60).padStart(2,"0")}`;
  $("runIdLabel").textContent = `Run ${job.id.slice(0,10)}`;
  const phases = {
    queued:"The request was accepted and is waiting to start.",
    running:"Preparing the request...",selecting:"허용된 경로에서 관련 소스 탐색 중...",
    selected:"관련 파일 탐색 완료.",generating:"관련 소스의 변경안 생성 중...",
    responding:"Claude Code is responding...",review:"Response received. Review the Diff before applying.",
    no_change:"Claude Code 호출 성공. 반환된 코드가 원본과 동일합니다. 판단 근거를 확인하고 필요하면 요청을 수정하세요.",
    needs_clarification:"Claude Code가 추가 설명을 요청했습니다. 대화를 확인하고 기능이나 변경 조건을 구체화해 다시 요청하세요.",
    applied:"Approved change applied to the workspace.",rejected:"Proposal rejected.",
    undone:"Source file restored.",failed:"Request failed. Review the error below and retry."
  };
  $("runSummary").textContent = job.error || phases[job.phase] || `Stage: ${job.phase}`;
  const list = $("runMessages");
  for (const event of job.events || []) {
    if (!Number.isFinite(event.seq) || event.seq <= state.lastEventSeq) continue;
    if (state.lastEventSeq === 0 && list.querySelector(".run-empty")) list.replaceChildren();
    const item = document.createElement("div"); item.className = `run-message ${event.role}`;
    const avatar = document.createElement("span"); avatar.className = "run-icon";
    avatar.textContent = ({user:"U",assistant:"C",system:"i",error:"!"})[event.role] || "i";
    const body = document.createElement("div"); body.className = "run-message-body";
    const head = document.createElement("div"); head.className = "run-message-head";
    const name = document.createElement("strong"); name.textContent = RUN_ROLE_LABELS[event.role] || "Execution";
    const when = document.createElement("time"); when.textContent = new Date(event.at).toLocaleTimeString("ko-KR");
    head.append(name,when);
    const msg = document.createElement("p"); msg.textContent = event.text;
    body.append(head,msg); item.append(avatar,body); list.append(item);
    state.lastEventSeq = event.seq;
  }
  if (expand) toggleRunConsole(true);
  if ((expand || state.activeRunId === job.id) && list.scrollHeight > list.clientHeight) list.scrollTop = list.scrollHeight;
}

async function showSavedRun(id) {
  try {
    const {job} = await request(`/api/jobs/${encodeURIComponent(id)}`);
    showRun(job, true);
    return job;
  } catch (error) {
    toast(`Conversation history unavailable: ${error.message}`, "error");
    return null;
  }
}

async function monitorRun(id) {
  state.activeRunId = id;
  let failures = 0;
  while (state.activeRunId === id) {
    try {
      const {job} = await request(`/api/jobs/${encodeURIComponent(id)}`);
      showRun(job, true);
      failures = 0;
      if (["complete","no_change","needs_clarification","failed"].includes(job.status)) {
        state.activeRunId = "";
        return job;
      }
    } catch (error) {
      failures++;
      $("runSummary").textContent = `Connection interrupted (${failures}). Reconnecting... ${error.message}`;
      if (failures >= 4) throw new Error("Unable to read job progress. Refresh to restore the run log.");
    }
    await new Promise(resolve => setTimeout(resolve, 850));
  }
  throw new Error("The displayed run was interrupted by navigation.");
}

async function restoreLastRun() {
  if (!state.workspace || state.busy) return;
  try {
    const {jobs} = await request("/api/jobs");
    const last = jobs.find(job => job.workspace === state.workspace);
    if (!last) return;
    showRun(last, last.status === "running");
    if (["running","queued"].includes(last.status)) {
      setBusy(true,"Claude Code is working...");
      try {
        const done = await monitorRun(last.id);
        if (["complete", "no_change", "needs_clarification"].includes(done.status) && done.proposal_id) {
          state.proposal = (await request("/api/proposal", {id:done.proposal_id})).proposal;
          changeTab("diff"); renderReview(); await loadHistory();
        }
      } finally {setBusy(false);}
    } else if (["no_change", "needs_clarification"].includes(last.status) && last.proposal_id && !state.proposal) {
      state.proposal = (await request("/api/proposal", {id:last.proposal_id})).proposal;
      changeTab("diff"); renderReview(); await loadHistory();
    }
  } catch(error) { toast(error.message,"error"); }
}

function toast(message, variant = "info") {
  const el = document.createElement("div");
  el.className = `toast ${variant}`;
  el.textContent = message;
  $("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

function setBusy(busy, text = "변경안 생성하기") {
  state.busy = busy;
  $("generateBtn").disabled = busy || !state.configured;
  $("connectWorkspace").disabled = busy;
  // File discovery is driven exclusively by the saved editable-path scope.
  $("generateText").textContent = text;
  $("generateBtn").querySelector(".btn-sparkle").textContent = busy ? "◌" : "✦";
  renderReview();
}

function setSteps(level) {
  for (let i = 1; i <= 4; i++) {
    const el = $(`step${i}`);
    el.classList.toggle("completed", i < level);
    el.classList.toggle("active", i === level);
    el.querySelector(".step-circle").textContent = i < level ? "✓" : String(i);
  }
}

async function refreshClaudeStatus() {
  $("claudeStatus").textContent = "Claude Code CLI 설치 상태 확인 중...";
  try {
    const result = await request("/api/claude/status");
    $("claudeStatus").textContent = result.note;
    $("claudeStatus").classList.toggle("ready", Boolean(result.installed));
  } catch (err) { $("claudeStatus").textContent = err.message; }
}

async function connectWorkspace(pathOverride = null, keepSettings = false) {
  const path = (typeof pathOverride === "string" ? pathOverride : $("workspaceInput").value).trim();
  if (!path) return toast("워크스페이스 경로를 입력하세요.", "error");
  $("connectWorkspace").disabled = true;
  try {
    const data = await request("/api/workspace", { path });
    state.workspace = data.path;
    state.files = data.files;
    state.scan = data.scan || null;
    resetEditableFileBrowsers();
    state.proposal = null;
    $("workspaceScanStatus").textContent = formatScanStatus(state.scan);
    $("workspaceScanStatus").classList.toggle("warning", scanNeedsAttention(state.scan));
    $("workspaceInput").value = data.path;
    populateEnvironment(data);
    renderEditableFileBrowser("code");
    $("workspacePill").textContent = data.configured ? "CONFIGURED" : "SETUP REQUIRED";
    $("workspacePill").classList.add("online");
    $("branchValue").textContent = data.branch;
    $("fileCount").textContent = String(data.files.length);
    state.previewFile = "";
    $("generateBtn").disabled = !state.configured || state.busy;
    renderReview();
    renderPreview();
    await loadInbox();
    showPage(!data.configured || keepSettings ? "settings" : "code", true);
    toast(data.configured
      ? `${data.name} 연결 · 수정 허용 파일 ${data.files.length}개` + (data.scan?.truncated ? " · 탐색 제한" : "")
      : `${data.name} 연결 · 환경 설정을 먼저 저장하세요.`,
      data.configured && !scanNeedsAttention(data.scan) ? "success" : "info");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    $("connectWorkspace").disabled = state.busy;
  }
}

function updateFileLabel(file) {
  const name = file || "허용 경로 기반 자동 탐색";
  $("filePathLabel").textContent = name;
  const ext = file && file.includes(".") ? file.split(".").pop().toUpperCase() : "—";
  $("fileLang").textContent = ext;
}

function showEmpty(message = "새로운 변경을 시작하세요", subtext = "요청을 작성하면 개발 환경의 수정 허용 경로에서 관련 파일을 찾아 변경안을 생성합니다.") {
  const container = $("diffBody");
  container.replaceChildren();
  const wrap = document.createElement("div"); wrap.className = "empty-diff";
  const icon = document.createElement("div"); icon.className = "empty-diff-icon";
  const iconText = document.createElement("span"); iconText.textContent = "{ }"; icon.appendChild(iconText);
  const h = document.createElement("h3"); h.textContent = message;
  const p = document.createElement("p"); p.textContent = subtext; p.style.whiteSpace = "pre-line";
  const caption = document.createElement("span"); caption.className = "empty-caption"; caption.textContent = "BEFORE APPLYING TO YOUR REPOSITORY";
  wrap.append(icon,h,p,caption); container.appendChild(wrap);
}

function renderLine(container, type, index, text) {
  const row = document.createElement("div"); row.className = `code-line ${type}`;
  const number = document.createElement("div"); number.className = "line-num"; number.textContent = String(index);
  const code = document.createElement("div"); code.className = "line-text"; code.textContent = text || " ";
  row.append(number, code); container.appendChild(row);
}

function renderPlain(content) {
  const wrap = document.createElement("div"); wrap.className = "diff-code";
  const lines = content.split(/\r?\n/);
  if (lines.length > 1 && lines[lines.length-1] === "") lines.pop();
  lines.forEach((line,i) => renderLine(wrap, "context", i+1, line));
  const body = $("diffBody"); body.replaceChildren(wrap); body.scrollTop = 0;
}

function renderDiff(diff) {
  if (!diff.length) return showEmpty("변경 사항 없음", "Claude Code가 현재 파일과 동일한 코드를 반환했습니다.\n판단 근거를 확인하고 요청을 수정해 다시 생성하세요.");
  const wrap = document.createElement("div"); wrap.className = "diff-code";
  let oldLine = 0, newLine = 0;
  for (const change of diff) {
    if (change.kind === "hunk") {
      const match = change.text.match(/^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)/);
      if (match) { oldLine = Number(match[1]); newLine = Number(match[2]); }
      renderLine(wrap, "hunk", "·", change.text);
    } else if (change.kind === "meta") {
      renderLine(wrap, "meta", "·", change.text);
    } else if (change.kind === "add") {
      renderLine(wrap, "add", newLine++, change.text);
    } else if (change.kind === "remove") {
      renderLine(wrap, "remove", oldLine++, change.text);
    } else {
      renderLine(wrap, "context", newLine++, change.text); oldLine++;
    }
  }
  const body = $("diffBody"); body.replaceChildren(wrap); body.scrollTop = 0;
}

function setDiffHeader(proposal) {
  const stats = $("diffStats"); stats.replaceChildren();
  if (!proposal) {
    const empty = document.createElement("span"); empty.className = "empty-stat"; empty.textContent = "No changes";
    stats.appendChild(empty);
    $("fileStatus").innerHTML = '<span class="status-idle-dot"></span> AWAITING TASK';
    $("diffFooterMessage").textContent = "변경 사항을 기다리는 중";
    return;
  }
  for (const [value, kind] of [[`+${proposal.plus}`, "plus"],[`-${proposal.minus}`, "minus"]]) {
    const pill = document.createElement("span"); pill.className = `stat-pill ${kind}`; pill.textContent = value; stats.appendChild(pill);
  }
  const status = { review: "READY FOR REVIEW", no_change: "NO CHANGES", needs_clarification: "NEEDS DETAILS", applied: "APPLIED", rejected: "REJECTED", undone: "UNDONE" }[proposal.status] || "REVIEW";
  $("fileStatus").textContent = `● ${status}`;
  $("fileStatus").style.color = proposal.status === "applied" ? "#1caa78" : proposal.status === "no_change" ? "#976413" : "#8b7ada";
  $("diffFooterMessage").textContent = proposal.status === "review" ? "검토 후 승인하거나 반려하세요" :
    proposal.status === "applied" ? "승인된 변경안이 파일에 반영되었습니다" :
    proposal.status === "undone" ? "변경을 이전 내용으로 되돌렸습니다" :
    proposal.status === "no_change" ? "Claude Code 호출 성공 · 원본 코드와 동일 · 파일 미수정" :
    proposal.status === "needs_clarification" ? "Claude Code가 요청의 추가 설명을 기다립니다 · 파일 미수정" : "제안을 반려했습니다. 파일을 수정하지 않았습니다";
}

function renderPreview() {
  const proposal = state.proposal;
  const files = proposal?.files || [];
  const chosen = files.find(f => f.path === state.previewFile) || files[0] || null;
  const selector = $("reviewFileSelect");
  const bar = $("reviewFilesBar");
  bar.classList.toggle("hidden", files.length < 2);
  selector.replaceChildren();
  for (const file of files) selector.add(new Option(`${file.code_changed ? "●" : "="} ${file.path}`, file.path));
  if (chosen) { selector.value = chosen.path; state.previewFile = chosen.path; }
  $("reviewFilesCount").textContent = `${files.filter(f => f.code_changed).length}/${files.length}개 변경`;
  updateFileLabel(chosen?.path || proposal?.target || "");
  setDiffHeader(proposal);
  if (proposal) {
    if (proposal.status === "needs_clarification") {
      showEmpty("추가 설명이 필요합니다", proposal.question || proposal.rationale || "요청을 조금 더 구체적으로 작성해 주세요.");
    } else if (chosen) {
      if (state.activeTab === "original") renderPlain(chosen.original_content);
      else if (state.activeTab === "revised") renderPlain(chosen.new_content);
      else renderDiff(chosen.diff || []);
    }
    return;
  }
  if (state.activeTab === "diff") {
    if (state.requestMode === "agent")
      showEmpty("수신 작업을 선택하세요", "에이전트 수신함에서 작업을 선택해 변경안을 생성하거나 불러오세요.");
    else showEmpty();
  } else {
    showEmpty("변경안 생성 전", "Claude Code가 관련 파일을 선택하면 원본과 변경 후 파일을 볼 수 있습니다.");
  }
}

function changeTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".tab-button").forEach(el => {
    const active = el.dataset.tab === tab;
    el.classList.toggle("active", active);
    el.setAttribute("aria-selected", active ? "true" : "false");
  });
  renderPreview();
}

function renderReview() {
  const p = state.proposal;
  const inReview = p && p.status === "review";
  const hasDetails = Boolean(p);
  $("reviewStatus").classList.toggle("hidden", inReview);
  $("reviewContent").classList.toggle("hidden", !hasDetails);
  $("retryRequestBtn").classList.toggle("hidden", !p || !["no_change", "needs_clarification"].includes(p.status));
  $("applyBtn").disabled = true;
  $("rejectBtn").disabled = !inReview || state.busy;
  $("undoBtn").disabled = !p || p.status !== "applied" || state.busy;
  if (!hasDetails) {
    $("reviewStatus").className = "review-status";
    $("reviewStatus").innerHTML = '<div class="review-status-icon">⋯</div><strong>승인 대기 없음</strong><p>변경안이 생성되면<br>여기에 검토 항목이 표시됩니다.</p>';
    setSteps(1);
    return;
  }
  const provenance = $("proposalProvenance");
  const byAgent = p.origin === "agent";
  const kind = SOURCE_LABELS[p.source_kind] || SOURCE_LABELS.freeform;
  provenance.replaceChildren();
  const label = document.createElement("strong");
  label.textContent = byAgent ? `에이전트 인계 · ${p.source_agent}` : "직접 요청";
  const detail = document.createElement("span");
  detail.textContent = [kind, p.source_ref, p.upstream_run_id,
    p.file_count ? `자동 탐색: ${p.file_count}개 관련 파일` : "추가 정보 요청"]
    .filter(Boolean).join(" · ");
  provenance.append(label, detail);
  $("proposalSummary").textContent = p.summary;
  $("proposalRationale").textContent = p.rationale;
  $("proposalRisk").textContent = p.risk;
  $("reviewChecklist").replaceChildren();
  const checks = Array.isArray(p.checks) ? p.checks : [];
  $("reviewGuidance").replaceChildren();
  for (const item of checks) {
    const div = document.createElement("div"); div.className = "guidance-row";
    const bullet = document.createElement("span"); bullet.textContent = "•";
    const label = document.createElement("span"); label.textContent = item;
    div.append(bullet, label); $("reviewGuidance").appendChild(div);
  }
  if (inReview) {
    setSteps(3);
    const reviewItems = ["모든 변경 파일의 Diff를 확인",
                         "영향 범위와 실패 경로 검토",
                         "실제 빌드·테스트는 아직 실행되지 않았음을 확인"];
    for (const check of reviewItems) {
      const label = document.createElement("label"); label.className = "check-row";
      const input = document.createElement("input"); input.type = "checkbox"; input.className = "review-check";
      input.addEventListener("change", () => {
        const all = [...document.querySelectorAll(".review-check")];
        $("applyBtn").disabled = state.busy || !all.every(el => el.checked);
      });
      const span = document.createElement("span"); span.textContent = check;
      label.append(input,span); $("reviewChecklist").appendChild(label);
    }
  } else {
    setSteps(p.status === "applied" ? 4 : 3);
    $("reviewStatus").className = `review-status ${p.status}`;
    const messages = {
      no_change: ["=", "Claude Code 정상 응답 · 변경 없음", "호출에는 성공했지만 현재 파일과 동일한 코드가 반환됐습니다. 아래 판단 근거를 확인한 뒤 요청을 수정하세요. 파일은 변경되지 않았습니다."],
      needs_clarification: ["?", "Claude Code 추가 설명 요청", "Claude Code가 개발할 파일을 충분히 판단하지 못했습니다. 파일을 직접 고를 필요 없이 수정할 기능이나 동작을 더 구체적으로 설명해 주세요."],
      applied: ["✓", "파일 반영 완료", "승인된 내용을 실제 소스에 반영했습니다."],
      rejected: ["×", "제안 반려 완료", "원본 파일은 변경되지 않았습니다."],
      undone: ["↺", "파일 되돌리기 완료", "제안 적용 전 파일 내용으로 복원했습니다."]
    };
    const [symbol,title,desc] = messages[p.status] || ["·","검토 종료",""];
    $("reviewStatus").replaceChildren();
    const icon = document.createElement("div"); icon.className = "review-status-icon"; icon.textContent = symbol;
    const strong = document.createElement("strong"); strong.textContent = title;
    const para = document.createElement("p"); para.textContent = desc;
    $("reviewStatus").append(icon,strong,para);
  }
}

async function generate() {
  if (state.busy) return;
  if (!state.workspace) return toast("Connect a workspace first.", "error");
  if (!state.configured) return showPage("settings");
  // No target file input: the model discovers relevant files within environment scope.
  const prompt = $("taskPrompt").value.trim();
  const source_kind = $("requestKind").value;
  const source_ref = $("requestRef").value.trim();
  const source_content = $("requestContent").value.trim();
  if (!state.files.length) return toast("No editable files. Review the environment configuration.", "error");
  if (source_kind !== "freeform" && source_content.length < 10) {
    $("requestContent").focus();
    return toast("Paste the reference document text (at least 10 characters).", "error");
  }
  if (prompt.length < 5) { $("taskPrompt").focus(); return toast("Describe the task in at least 5 characters.", "error"); }
  state.proposal = null;
  renderPreview(); renderReview();
  setBusy(true, "허용된 범위에서 코드 탐색 및 개발 중...");
  setSteps(2);
  showSubmitting(prompt);
  try {
    const {job} = await request("/api/jobs", {workspace: state.workspace, prompt,
      source_kind, source_ref, source_content});
    showRun(job, true);
    const finished = await monitorRun(job.id);
    if (!["complete", "no_change", "needs_clarification"].includes(finished.status)) throw new Error(finished.error || "Claude Code job failed");
    state.proposal = (await request("/api/proposal", {id: finished.proposal_id})).proposal;
    state.previewFile = "";
    changeTab("diff"); renderReview(); await loadHistory();
    toast(state.proposal.status === "needs_clarification" ?
      "Claude Code가 추가 설명을 요청했습니다. 대화 패널을 확인하세요." :
      state.proposal.status === "no_change" ? "Claude Code 호출 성공 · 변경 없음. 응답 근거를 확인하세요." :
      `변경 파일 ${state.proposal.changed_files?.length || 0}개 · Diff를 검토한 후 승인하세요.`,
      ["no_change", "needs_clarification"].includes(state.proposal.status) ? "info" : "success");
  } catch (err) {
    showRunError(err.message);
    toast(err.message, "error");
  } finally {
    setBusy(false);
  }
}

function retryNoChange() {
  const p = state.proposal;
  if (!p || !["no_change", "needs_clarification"].includes(p.status) || state.busy) return;
  // This always creates a new human request; agent handoff provenance is not impersonated.
  setRequestMode("human");
  $("taskPrompt").value = p.prompt;
  if (p.status === "needs_clarification" && p.question) {
    $("taskPrompt").value = p.prompt + "\n\n추가 설명: ";
  }
  if (p.origin === "agent") {
    $("requestKind").value = "freeform";
    updateReferenceFields();
  }
  $("taskPrompt").focus();
  $("taskPrompt").scrollIntoView({behavior: "smooth", block: "center"});
  toast("기존 요청을 가져왔습니다. 변경 조건을 구체화한 뒤 다시 생성하세요.");
}

async function performAction(action) {
  if (!state.proposal || state.busy) return;
  let question = "";
  if (action === "apply") question = `다음 ${state.proposal.changed_files?.length || 0}개 파일을 실제로 변경하시겠습니까?\n\n${(state.proposal.changed_files || []).join("\n")}\n\n해당 파일이 워크스페이스에 즉시 반영됩니다.`;
  else if (action === "undo") question = "현재 파일을 이번 작업의 적용 전 내용으로 복원하시겠습니까?";
  else question = "이 변경안을 반려하시겠습니까? 원본 파일은 수정되지 않습니다.";
  if (!window.confirm(question)) return;
  state.busy = true;
  $("applyBtn").disabled = true;
  $("rejectBtn").disabled = true;
  $("undoBtn").disabled = true;
  try {
    const result = await request(`/api/${action}`, { id: state.proposal.id });
    state.proposal = result.proposal;
    renderReview(); renderPreview(); await loadHistory(); await loadInbox();
    if (state.proposal.job_id) await showSavedRun(state.proposal.job_id);
    toast(action === "apply" ? "승인된 변경을 로컬 소스에 반영했습니다." : action === "undo" ? "적용 전 내용으로 복원했습니다." : "제안을 반려했습니다.", "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    state.busy = false;
    renderReview();
  }
}

async function loadHistory() {
  try {
    const {history} = await request("/api/history");
    $("historyCounter").textContent = `${history.length} runs`;
    const root = $("historyList"); root.replaceChildren();
    if (!history.length) {
      const none = document.createElement("div"); none.className = "no-history";
      none.textContent = "아직 실행한 변경 작업이 없습니다. 위에서 첫 요청을 생성해보세요.";
      root.appendChild(none); return;
    }
    const icons = {review:"≠",no_change:"=",needs_clarification:"?",applied:"✓",rejected:"×",undone:"↺"};
    const names = {review:"REVIEW",no_change:"NO CHANGES",needs_clarification:"NEEDS DETAILS",applied:"APPLIED",rejected:"REJECTED",undone:"UNDONE"};
    for (const item of history) {
      const button = document.createElement("button"); button.type = "button";
      button.className = `history-row ${state.proposal && item.id === state.proposal.id ? "selected" : ""}`;
      const icon = document.createElement("div"); icon.className = `history-icon ${item.status}`; icon.textContent = icons[item.status] || "≠";
      const content = document.createElement("div"); content.className = "history-content";
      const title = document.createElement("div"); title.className = "history-title"; title.textContent = item.summary;
      const path = document.createElement("div"); path.className = "history-path";
      path.textContent = `${item.target} · ${item.origin === "agent" ? item.source_agent : "직접 요청"} / ${SOURCE_LABELS[item.source_kind] || "자유 요청"} · ${new Date(item.created_at).toLocaleString("ko-KR")}`;
      content.append(title,path);
      const chip = document.createElement("span"); chip.className = `history-status ${item.status}`; chip.textContent = names[item.status] || item.status;
      button.append(icon,content,chip);
      button.addEventListener("click", async () => {
        if (state.busy) return;
        try {
          const result = await request("/api/proposal", {id: item.id});
          state.proposal = result.proposal;
          changeTab("diff"); renderReview(); await loadHistory();
          if (state.proposal.job_id) await showSavedRun(state.proposal.job_id);
          if (state.proposal.origin === "agent") setRequestMode("agent");
          window.scrollTo({top: 0,behavior:"smooth"});
        } catch (error) { toast(error.message, "error"); }
      });
      root.appendChild(button);
    }
  } catch (error) { toast(error.message, "error"); }
}

async function initialize() {
  $("fillSamplePrompt").addEventListener("click", () => { $("taskPrompt").value = SAMPLE_PROMPT; $("taskPrompt").focus(); });
  $("modeHuman").addEventListener("click", () => setRequestMode("human"));
  $("modeAgent").addEventListener("click", () => setRequestMode("agent"));
  $("requestKind").addEventListener("change", updateReferenceFields);
  $("refreshInbox").addEventListener("click", loadInbox);
  $("inboxAction").addEventListener("click", openIncoming);
  updateReferenceFields();
  $("connectWorkspace").addEventListener("click", connectWorkspace);
  $("workspaceInput").addEventListener("keydown", event => { if (event.key === "Enter") connectWorkspace(); });
  $("envEditShortcut").addEventListener("click", () => showPage("settings"));
  $("activeEnvEdit").addEventListener("click", () => showPage("settings"));
  $("navCodeDev").addEventListener("click", () => showPage("code"));
  $("navEnvironment").addEventListener("click", () => showPage("settings"));
  $("envBackBtn").addEventListener("click", () => showPage("code"));
  $("envLoadWorkspace").addEventListener("click", () => connectWorkspace($("envWorkspacePath").value, true));
  $("envSaveBtn").addEventListener("click", saveEnvironment);
  setupEditableFileBrowserEvents();
  $("envRestoreBtn").addEventListener("click", () => {
    if (!state.config) return;
    for (const [key, id] of Object.entries(PROFILE_FIELDS)) $(id).value = state.config[key] || "";
    $("envWorkspacePath").value = state.workspace || "";
    renderEnvironmentSummary();
    toast("마지막으로 불러온 설정으로 복원했습니다.");
  });
  $("envTemplateKernel").addEventListener("click", () => applyEnvironmentTemplate("kernel"));
  $("envTemplateGeneric").addEventListener("click", () => applyEnvironmentTemplate("generic"));
  document.querySelectorAll("#settingsView input, #settingsView textarea, #settingsView select")
    .forEach(el => { if (el.id !== "envEditableSearch") el.addEventListener("input", renderEnvironmentSummary); });
  $("generateBtn").addEventListener("click", generate);
  $("runConsoleToggle").addEventListener("click", () => {
    toggleRunConsole($("runConsoleBody").classList.contains("hidden"));
  });
  $("retryRequestBtn").addEventListener("click", retryNoChange);
  $("applyBtn").addEventListener("click", () => performAction("apply"));
  $("rejectBtn").addEventListener("click", () => performAction("reject"));
  $("undoBtn").addEventListener("click", () => performAction("undo"));
  $("refreshClaude").addEventListener("click", refreshClaudeStatus);
  $("reviewFileSelect").addEventListener("change", event => {
    state.previewFile = event.target.value;
    renderPreview();
  });
  document.querySelectorAll("[data-tab]").forEach(el => el.addEventListener("click",() => changeTab(el.dataset.tab)));
  $("taskPrompt").value = "";
  try {
    const response = await request("/api/bootstrap");
    state.token = response.token;
    await refreshClaudeStatus();
    $("serverSideStatus").textContent = `${window.location.host} · 연결됨`;
    state.configFile = response.config_file;
    state.agentIntakeEnabled = Boolean(response.agent_intake_enabled);
    $("agentIntakeStatus").textContent = state.agentIntakeEnabled
      ? "에이전트 API 연결 활성 · 별도 토큰으로 작업 수신" : "수신 API 비활성 · AX_AGENT_TOKEN 설정 후 서버를 다시 시작하세요";
    $("envConfigLocation").textContent = response.config_file;
    $("workspaceInput").value = response.last_workspace || response.sample_path;
    await connectWorkspace();
    if (state.workspace === response.sample_path) $("taskPrompt").value = SAMPLE_PROMPT;
    if (!state.workspace && response.last_workspace) {
      $("workspaceInput").value = response.sample_path;
      await connectWorkspace();
    }
    await loadHistory();
    await restoreLastRun();
  } catch (error) {
    $("serverSideStatus").textContent = "서버 연결 실패";
    toast(error.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", initialize);
