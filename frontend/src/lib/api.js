// API client for the Wave-o-meter backend (SDD §10).
// In dev, Vite proxies /api -> FastAPI. In prod, backend serves this app so
// the relative path just works.

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const getOverview = () => getJSON('/api/overview');
export const getForecast = (id) => getJSON(`/api/spots/${id}/forecast`);
export const getSpots = () => getJSON('/api/spots');
export const getSummary = () => getJSON('/api/summary');
export const getBuoys = () => getJSON('/api/buoys');

// --- access gate ---
export const getGateStatus = () => getJSON('/api/gate/status');
export async function submitGateAnswer(answer) {
  const res = await fetch('/api/gate/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer })
  });
  return { status: res.status, ...(await res.json()) };
}
