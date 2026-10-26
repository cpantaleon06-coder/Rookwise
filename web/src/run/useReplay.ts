import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Replayer, type Speed } from "../lib/replay";
import { applyEvents, initialRunState, type RunState } from "../lib/runState";
import type { RunEvent, TimedEvent } from "../lib/types";

interface ReplayState {
  run: RunState;
  playing: boolean;
  done: boolean;
}

type Action =
  | { type: "apply"; events: RunEvent[] }
  | { type: "reset"; playing: boolean; done: boolean }
  | { type: "status"; playing: boolean; done?: boolean };

function reducer(state: ReplayState, action: Action): ReplayState {
  switch (action.type) {
    case "apply":
      return { ...state, run: applyEvents(state.run, action.events) };
    case "reset":
      return { run: initialRunState(), playing: action.playing, done: action.done };
    case "status":
      return { ...state, playing: action.playing, done: action.done ?? state.done };
  }
}

function initial(): ReplayState {
  return { run: initialRunState(), playing: false, done: false };
}

export interface ReplayControls {
  state: RunState;
  speed: Speed;
  playing: boolean;
  done: boolean;
  position: number;
  total: number;
  play: () => void;
  pause: () => void;
  setSpeed: (speed: Speed) => void;
  restart: () => void;
  skipToEnd: () => void;
}

/** Plays `events` into a RunState, starting on mount. */
export function useReplay(events: TimedEvent[], initialSpeed: Speed = "1x"): ReplayControls {
  const [{ run: state, playing, done }, dispatch] = useReducer(reducer, undefined, initial);
  const [speed, setSpeedState] = useState<Speed>(initialSpeed);
  const replayer = useRef<Replayer | null>(null);
  const speedRef = useRef(initialSpeed);

  useEffect(() => {
    dispatch({ type: "reset", playing: events.length > 0, done: events.length === 0 });
    const r = new Replayer(events, {
      speed: speedRef.current,
      onEvents: (batch) => dispatch({ type: "apply", events: batch }),
      onDone: () => dispatch({ type: "status", playing: false, done: true }),
    });
    replayer.current = r;
    r.play();
    return () => {
      r.dispose();
      replayer.current = null;
    };
  }, [events]);

  const play = useCallback(() => {
    const r = replayer.current;
    if (!r || r.isDone) return;
    dispatch({ type: "status", playing: true });
    r.play();
  }, []);

  const pause = useCallback(() => {
    replayer.current?.pause();
    dispatch({ type: "status", playing: false });
  }, []);

  const setSpeed = useCallback((next: Speed) => {
    speedRef.current = next;
    setSpeedState(next);
    replayer.current?.setSpeed(next);
  }, []);

  const restart = useCallback(() => {
    const r = replayer.current;
    if (!r) return;
    r.restart();
    dispatch({ type: "reset", playing: r.length > 0, done: r.length === 0 });
    r.play();
  }, []);

  const skipToEnd = useCallback(() => {
    replayer.current?.skipToEnd();
  }, []);

  return {
    state,
    speed,
    playing,
    done,
    position: state.applied.length,
    total: events.length,
    play,
    pause,
    setSpeed,
    restart,
    skipToEnd,
  };
}
