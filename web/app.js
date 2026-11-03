"use strict";

const state = {
  token: null,
  workspace: null,
  files: [],
  target: "",
  engine: "demo",
  proposal: null,
  activeTab: "diff",
  model: "",
  busy: false,
  configured: false,
  config: null,
  configBase: "",
  page: "code",
  configFile: "",
};
const $ = (id) => document.getElementById(id);
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
  $("currentPageName").textContent = page === "settings" ? "Development Environment" : "Code-Dev Agent";
  window.scrollTo({top: 0, behavior: "instant"});
}

function envFromForm() {
  const result = {};
  for (const [key, elementId] of Object.entries(PROFILE_FIELDS)) result[key] = $(elementId).value.trim();
  return result;
}

function renderEnvironmentSummary() {
  const data = envFromForm();
  $("envSummaryName").textContent = data.project_name || "프로젝트명 미설정";
  $("envSummaryPath").textContent = $("envWorkspacePath").value.trim() || "Workspace 연결 필요";
  $("envSummaryType").textContent = data.project_type === "linux-kernel" ? "Linux Kernel Driver" : "Generic project";
  $("envSummaryBuildDir").textContent = data.build_dir || ".";
  $("envSummaryCommand").textContent = data.build_command || "명령어를 입력하세요.";
  $("envSummaryScope").textContent = data.editable_paths || "경로 패턴을 입력하세요.";
  const dirty = JSON.stringify(data) !== state.configBase || $("envWorkspacePath").value.trim() !== state.workspace;
  $("envUnsaved").textContent = !state.configured ? "초기 환경 설정이 필요합니다" :
    dirty ? "변경사항 미저장 · 저장 후 적용" : "모든 설정 저장됨";
  $("envUnsaved").classList.toggle("unsaved", dirty || !state.configured);
  $("envSummaryConfig").textContent = !state.configured ? "아직 설정되지 않은 프로젝트" :
    dirty ? "현재 입력은 저장되지 않았습니다" : "저장된 프로젝트 프로필";
  $("envSummaryFiles").textContent = !state.configured || dirty ? "저장 후 계산" :
    `${state.files.length}개 파일`;
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
    toast(`환경 설정 저장 완료 · 수정 허용 ${result.editable_files}개 파일`, "success");
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
  $("targetFile").disabled = busy;
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

function setEngine(engine) {
  state.engine = engine;
  document.querySelectorAll("[data-engine]").forEach(el => {
    const active = el.dataset.engine === engine;
    el.classList.toggle("selected", active);
    el.setAttribute("aria-pressed", active ? "true" : "false");
  });
  $("ollamaConfig").classList.toggle("hidden", engine !== "ollama");
  $("submitNote").textContent = engine === "demo"
    ? "데모 모드: 예제 파일에 고정된 변경안을 보여줍니다. LLM은 호출하지 않습니다."
    : "Ollama는 127.0.0.1에 설치되어 있어야 합니다. 외부 AI API는 호출하지 않습니다.";
  if (engine === "ollama") refreshModels();
}

async function refreshModels() {
  $("ollamaStatus").textContent = "로컬 Ollama 연결 확인 중...";
  try {
    const result = await request("/api/models");
    const select = $("modelSelect");
    select.replaceChildren();
    if (!result.online) {
      const option = new Option("Ollama 오프라인 · ollama serve 필요", "");
      select.add(option);
      $("ollamaStatus").textContent = `서버에 연결할 수 없습니다 (${result.endpoint}).`;
      return;
    }
    if (!result.models.length) {
      select.add(new Option("설치된 Ollama 모델 없음", ""));
      $("ollamaStatus").textContent = "모델 설치 후 새로고침하세요 (예: ollama list).";
      return;
    }
    for (const name of result.models) select.add(new Option(name, name));
    if (state.model && result.models.includes(state.model)) select.value = state.model;
    state.model = select.value;
    $("ollamaStatus").textContent = `${result.models.length}개 모델 감지 · ${result.endpoint}`;
  } catch (err) {
    $("ollamaStatus").textContent = err.message;
  }
}

async function connectWorkspace(pathOverride = null, keepSettings = false) {
  const path = (typeof pathOverride === "string" ? pathOverride : $("workspaceInput").value).trim();
  if (!path) return toast("워크스페이스 경로를 입력하세요.", "error");
  $("connectWorkspace").disabled = true;
  try {
    const data = await request("/api/workspace", { path });
    state.workspace = data.path;
    state.files = data.files;
    state.proposal = null;
    $("workspaceInput").value = data.path;
    populateEnvironment(data);
    $("workspacePill").textContent = !data.configured ? "SETUP REQUIRED" :
      data.is_demo ? "DEMO · CONFIGURED" : "CONFIGURED";
    $("workspacePill").classList.add("online");
    $("branchValue").textContent = data.branch;
    $("fileCount").textContent = String(data.files.length);
    const select = $("targetFile");
    select.replaceChildren();
    if (!data.files.length) select.add(new Option("지원하는 텍스트 소스 파일 없음", ""));
    for (const file of data.files) select.add(new Option(file.path, file.path));
    const favored = data.files.find(f => f.path === "drivers/power/supply/ax_ifpmic_charger.c");
    if (favored) select.value = favored.path;
    state.target = select.value;
    $("generateBtn").disabled = !state.configured || state.busy;
    renderReview();
    renderPreview();
    showPage(!data.configured || keepSettings ? "settings" : "code", true);
    toast(data.configured ? `${data.name} 연결 · 수정 허용 파일 ${data.files.length}개` :
      `${data.name} 연결 · 환경 설정을 먼저 저장하세요.`, data.configured ? "success" : "info");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    $("connectWorkspace").disabled = state.busy;
  }
}

function updateFileLabel(file) {
  const name = file || "No file selected";
  $("filePathLabel").textContent = name;
  const ext = name.includes(".") ? name.split(".").pop().toUpperCase() : "—";
  $("fileLang").textContent = ext;
}

function showEmpty(message = "새로운 변경을 시작하세요", subtext = "왼쪽에서 요청과 대상 파일을 선택하면\n에이전트의 변경안을 여기에서 비교할 수 있습니다.") {
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
  const status = { review: "READY FOR REVIEW", applied: "APPLIED", rejected: "REJECTED", undone: "UNDONE" }[proposal.status] || "REVIEW";
  $("fileStatus").textContent = `● ${status}`;
  $("fileStatus").style.color = proposal.status === "applied" ? "#1caa78" : "#8b7ada";
  $("diffFooterMessage").textContent = proposal.status === "review" ? "검토 후 승인하거나 반려하세요" :
    proposal.status === "applied" ? "승인된 변경안이 파일에 반영되었습니다" :
    proposal.status === "undone" ? "변경을 이전 내용으로 되돌렸습니다" : "제안을 반려했습니다. 파일을 수정하지 않았습니다";
}

function renderPreview() {
  updateFileLabel(state.proposal ? state.proposal.target : state.target);
  const proposal = state.proposal;
  setDiffHeader(proposal);
  if (proposal) {
    if (state.activeTab === "original") renderPlain(proposal.original_content);
    else if (state.activeTab === "revised") renderPlain(proposal.new_content);
    else renderDiff(proposal.diff);
    return;
  }
  if (state.activeTab === "diff") {
    showEmpty();
    return;
  }
  if (!state.target || !state.workspace) return showEmpty();
  // Before proposal generation Original/Revised both show read-only source.
  request("/api/file", { workspace: state.workspace, target: state.target })
    .then(data => { if (!state.proposal) renderPlain(data.content); })
    .catch(err => toast(err.message, "error"));
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
  $("applyBtn").disabled = true;
  $("rejectBtn").disabled = !inReview || state.busy;
  $("undoBtn").disabled = !p || p.status !== "applied" || state.busy;
  if (!hasDetails) {
    $("reviewStatus").className = "review-status";
    $("reviewStatus").innerHTML = '<div class="review-status-icon">⋯</div><strong>승인 대기 없음</strong><p>변경안이 생성되면<br>여기에 검토 항목이 표시됩니다.</p>';
    setSteps(1);
    return;
  }
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
    const reviewItems = ["Diff 전체 및 의도하지 않은 변경 확인",
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
  if (!state.workspace) return toast("먼저 워크스페이스를 연결하세요.", "error");
  if (!state.configured) return showPage("settings");
  const target = $("targetFile").value;
  const prompt = $("taskPrompt").value.trim();
  if (!target) return toast("수정 대상 파일을 선택하세요.", "error");
  if (prompt.length < 5) return toast("작업 요청을 구체적으로 입력하세요.", "error");
  const model = $("modelSelect").value;
  if (state.engine === "ollama" && !model) return toast("Ollama 모델을 먼저 선택하세요.", "error");
  state.model = model;
  setBusy(true, state.engine === "ollama" ? "로컬 AI가 변경안 생성 중..." : "데모 변경안 생성 중...");
  try {
    const result = await request("/api/propose", { workspace: state.workspace, target, prompt, engine: state.engine, model });
    state.proposal = result.proposal;
    changeTab("diff");
    renderReview();
    await loadHistory();
    toast("변경안이 생성되었습니다. Diff 검토 후 승인해 주세요.", "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    setBusy(false);
  }
}

async function performAction(action) {
  if (!state.proposal || state.busy) return;
  let question = "";
  if (action === "apply") question = `다음 파일을 실제로 변경하시겠습니까?\n\n${state.proposal.target}\n\n해당 파일이 워크스페이스에 즉시 반영됩니다.`;
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
    renderReview(); renderPreview(); await loadHistory();
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
    const icons = {review:"≠",applied:"✓",rejected:"×",undone:"↺"};
    const names = {review:"REVIEW",applied:"APPLIED",rejected:"REJECTED",undone:"UNDONE"};
    for (const item of history) {
      const button = document.createElement("button"); button.type = "button";
      button.className = `history-row ${state.proposal && item.id === state.proposal.id ? "selected" : ""}`;
      const icon = document.createElement("div"); icon.className = `history-icon ${item.status}`; icon.textContent = icons[item.status] || "≠";
      const content = document.createElement("div"); content.className = "history-content";
      const title = document.createElement("div"); title.className = "history-title"; title.textContent = item.summary;
      const path = document.createElement("div"); path.className = "history-path";
      path.textContent = `${item.target} · ${item.engine.toUpperCase()} · ${new Date(item.created_at).toLocaleString("ko-KR")}`;
      content.append(title,path);
      const chip = document.createElement("span"); chip.className = `history-status ${item.status}`; chip.textContent = names[item.status] || item.status;
      button.append(icon,content,chip);
      button.addEventListener("click", async () => {
        if (state.busy) return;
        try {
          const result = await request("/api/proposal", {id: item.id});
          state.proposal = result.proposal;
          changeTab("diff"); renderReview(); await loadHistory();
          window.scrollTo({top: 0,behavior:"smooth"});
        } catch (error) { toast(error.message, "error"); }
      });
      root.appendChild(button);
    }
  } catch (error) { toast(error.message, "error"); }
}

async function initialize() {
  $("fillDemoPrompt").addEventListener("click", () => { $("taskPrompt").value = SAMPLE_PROMPT; $("taskPrompt").focus(); });
  $("connectWorkspace").addEventListener("click", connectWorkspace);
  $("workspaceInput").addEventListener("keydown", event => { if (event.key === "Enter") connectWorkspace(); });
  $("envEditShortcut").addEventListener("click", () => showPage("settings"));
  $("activeEnvEdit").addEventListener("click", () => showPage("settings"));
  $("navCodeDev").addEventListener("click", () => showPage("code"));
  $("navEnvironment").addEventListener("click", () => showPage("settings"));
  $("envBackBtn").addEventListener("click", () => showPage("code"));
  $("envLoadWorkspace").addEventListener("click", () => connectWorkspace($("envWorkspacePath").value, true));
  $("envSaveBtn").addEventListener("click", saveEnvironment);
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
    .forEach(el => el.addEventListener("input", renderEnvironmentSummary));
  $("generateBtn").addEventListener("click", generate);
  $("applyBtn").addEventListener("click", () => performAction("apply"));
  $("rejectBtn").addEventListener("click", () => performAction("reject"));
  $("undoBtn").addEventListener("click", () => performAction("undo"));
  $("refreshModels").addEventListener("click", refreshModels);
  $("targetFile").addEventListener("change", event => {
    state.target = event.target.value;
    state.proposal = null;
    renderPreview(); renderReview(); loadHistory();
  });
  document.querySelectorAll("[data-engine]").forEach(el => el.addEventListener("click",() => setEngine(el.dataset.engine)));
  document.querySelectorAll("[data-tab]").forEach(el => el.addEventListener("click",() => changeTab(el.dataset.tab)));
  $("taskPrompt").value = SAMPLE_PROMPT;
  setEngine("demo");
  try {
    const response = await request("/api/bootstrap");
    state.token = response.token;
    $("serverSideStatus").textContent = "127.0.0.1 · 연결됨";
    state.configFile = response.config_file;
    $("envConfigLocation").textContent = response.config_file;
    $("workspaceInput").value = response.last_workspace || response.demo_path;
    await connectWorkspace();
    if (!state.workspace && response.last_workspace) {
      $("workspaceInput").value = response.demo_path;
      await connectWorkspace();
    }
    await loadHistory();
  } catch (error) {
    $("serverSideStatus").textContent = "서버 연결 실패";
    toast(error.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", initialize);
