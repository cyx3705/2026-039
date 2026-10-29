// Load full reasoning only for the selected completed round.
let thoughtRun = null, thoughtCount = -1, thoughtKey = null, thoughtRequest = 0;
const thoughtEvents = new EventSource('/thought-stream');
thoughtEvents.onmessage = event => {
  const state = JSON.parse(event.data);
  const text = document.getElementById('liveThoughtText');
  const follow = text.scrollTop + text.clientHeight >= text.scrollHeight - 40;
  if (state.kind === 'delta') text.append(document.createTextNode(state.text));
  else text.textContent = state.text;
  if (follow) text.scrollTop = text.scrollHeight;
  const names = {idle:'空闲', thinking:'正在思考 · 实时输出', action:'正在生成动作', complete:'本轮生成完成', stopped:'已停止', error:'已中止'};
  document.getElementById('liveThoughtStatus').textContent =
    `${state.round ? '第 '+state.round+' 轮 · ' : ''}${names[state.status] ?? state.status}`;
};
thoughtEvents.onerror = () => {
  document.getElementById('liveThoughtStatus').textContent = '实时连接断开，正在重连…';
};
document.getElementById('stop').onclick = async () => {
  const button = document.getElementById('stop');
  button.disabled = true;
  try {
    const response = await fetch('/stop', {method:'POST'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    document.getElementById('liveThoughtStatus').textContent = '正在取消生成…';
  } catch (error) {
    document.getElementById('liveThoughtStatus').textContent = `停止失败：${error.message}`;
  } finally { button.disabled = false; }
};
function updateThoughts(doc) {
  const select = document.getElementById('thoughtRound');
  if (thoughtRun !== doc.run_id || thoughtCount !== doc.steps.length) {
    const selected = thoughtRun === doc.run_id ? select.value : 'latest';
    select.replaceChildren(new Option('跟随最新完成轮次', 'latest'));
    for (const step of doc.steps) select.add(new Option(`第 ${step.round} 轮`, String(step.round)));
    select.value = [...select.options].some(o => o.value === selected) ? selected : 'latest';
    thoughtRun = doc.run_id;
    thoughtCount = doc.steps.length;
  }
  select.onchange = () => { thoughtKey = null; updateThoughts(doc); };
  const round = select.value === 'latest' ? doc.steps.at(-1)?.round : Number(select.value);
  const key = `${doc.run_id}:${round}`;
  if (thoughtKey === key) return;
  thoughtKey = key;
  const request = ++thoughtRequest;
  const text = document.getElementById('thoughtText');
  const status = document.getElementById('thoughtStatus');
  if (!round) {
    status.textContent = doc.status === 'running' ? '等待首轮完成；完成后显示思考原文。' : '暂无已完成轮次。';
    text.textContent = '';
    return;
  }
  status.textContent = `第 ${round} 轮 · 加载中…`;
  text.textContent = '';
  fetch(`runs/${encodeURIComponent(doc.run_id)}.json`, {cache: 'no-store'})
    .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(full => {
      if (request !== thoughtRequest) return;
      const audit = full.steps.find(s => s.round === round)?.audit;
      const reasoning = audit?.reasoning_audit;
      text.textContent = reasoning?.response?.content ?? '这一轮未开启思考，或旧记录没有保存思考文本。';
      status.textContent = `第 ${round} 轮 · ${audit?.reasoning_tokens ?? 0} 思考 token · ` +
        (reasoning ? (reasoning.budget_hit ? '预算截停，由程序结束思考段' : '模型自然结束思考') : '无思考记录');
    })
    .catch(error => {
      if (request !== thoughtRequest) return;
      status.textContent = `加载失败：${error.message}`;
      thoughtKey = null;
    });
}
