// Live stream state, kept above the pages so the feed keeps running while you browse other tabs.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { API, post } from "./api";
import { useSettings } from "./settings";

const Ctx = createContext(null);
export const useLive = () => useContext(Ctx);
const FEED_MAX = 60, PULSE_MAX = 160;

export function LiveProvider({ children }) {
  const { currency } = useSettings();
  const [connected, setConnected] = useState(false);
  const [feed, setFeed] = useState([]);
  const [pulse, setPulse] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [replay, setReplay] = useState({ running: false, rate: 5, source: null, sent: 0 });
  const [totals, setTotals] = useState({ total: 0, flagged: 0 });
  const [threshold, setThresholdState] = useState(0.5);
  const buf = useRef([]);

  useEffect(() => {
    post("/api/stream/config", { currency }).catch(() => {});
  }, [currency]);

  useEffect(() => {
    let es, alive = true, retry;
    const open = () => {
      es = new EventSource(`${API}/api/stream`);
      es.onopen = () => alive && setConnected(true);
      es.onerror = () => { setConnected(false); es.close(); if (alive) retry = setTimeout(open, 2500); };
      es.addEventListener("snapshot", (e) => {
        const s = JSON.parse(e.data);
        setFeed(s.recent); setPulse(s.recent.map((r) => r.risk).reverse());
        setTotals({ total: s.total, flagged: s.flagged_total }); setThresholdState(s.threshold); setReplay(s.replay);
      });
      es.addEventListener("txn", (e) => buf.current.push(JSON.parse(e.data)));
      es.addEventListener("analysis", (e) => setAnalysis(JSON.parse(e.data)));
      es.addEventListener("replay", (e) => setReplay(JSON.parse(e.data)));
    };
    open();
    // events can arrive at 100+/s: batch them into one React update every 250 ms
    const flush = setInterval(() => {
      if (!buf.current.length) return;
      const batch = buf.current; buf.current = [];
      setFeed((f) => [...batch.slice().reverse(), ...f].slice(0, FEED_MAX));
      setPulse((p) => [...p, ...batch.map((b) => b.risk)].slice(-PULSE_MAX));
      setTotals((t) => ({ total: t.total + batch.length, flagged: t.flagged + batch.filter((b) => b.flagged).length }));
    }, 250);
    return () => { alive = false; clearTimeout(retry); clearInterval(flush); es && es.close(); };
  }, []);

  const startReplay = useCallback((source, rate) => {
    setFeed([]); setPulse([]); setAnalysis(null); setTotals({ total: 0, flagged: 0 });
    return post("/api/stream/replay", { action: "start", source, rate });
  }, []);
  const stopReplay = useCallback(() => post("/api/stream/replay", { action: "stop" }), []);
  const setRate = useCallback((rate) => post("/api/stream/replay", { action: "rate", rate }), []);
  const setThreshold = useCallback((t) => { setThresholdState(t); return post("/api/stream/config", { threshold: t }); }, []);
  const reset = useCallback(async () => {
    await post("/api/stream/reset", {});
    setFeed([]); setPulse([]); setAnalysis(null); setTotals({ total: 0, flagged: 0 });
  }, []);

  return (
    <Ctx.Provider value={{ connected, feed, pulse, analysis, replay, totals, threshold, startReplay, stopReplay, setRate, setThreshold, reset }}>
      {children}
    </Ctx.Provider>
  );
}
