"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";

/** 이만큼 끌면 넘어간다. */
const THRESHOLD = 74;
/** 이 안쪽 움직임은 드래그가 아니라 클릭으로 본다. */
const SLOP = 8;
/** 끌던 방향으로 마저 밀어내는 시간. 이 뒤에 다음 장이 들어온다. */
const FLING_MS = 170;

export interface SwipeDeck {
  index: number;
  /** 방금 어느 쪽에서 들어온 장인지. 들어오는 방향을 정한다. */
  from: "next" | "prev" | null;
  /** 한 번이라도 끌어 봤는지. 스와이프 안내를 지우는 데 쓴다. */
  touched: boolean;
  dragging: boolean;
  /** 현재 장의 카드에 얹는 인라인 변형. */
  cardStyle: CSSProperties;
  go: (next: number) => void;
  step: (delta: number) => void;
  /** deck 컨테이너에 펼쳐 넣는 핸들러. */
  handlers: {
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerMove: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerUp: (event: ReactPointerEvent<HTMLElement>) => void;
    onPointerCancel: (event: ReactPointerEvent<HTMLElement>) => void;
    onClickCapture: (event: { preventDefault: () => void; stopPropagation: () => void }) => void;
  };
}

/**
 * 카드 한 장씩 넘기는 덱.
 * 버튼 클릭과 드래그를 구분해야 하므로 SLOP 을 넘겨 움직인 뒤부터 드래그로 본다.
 * Pointer Events 로 마우스와 터치를 한 경로에서 처리한다.
 */
export function useSwipeDeck(count: number): SwipeDeck {
  const [index, setIndex] = useState(0);
  const [from, setFrom] = useState<"next" | "prev" | null>(null);
  const [touched, setTouched] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [offset, setOffset] = useState(0);
  /** 밀어내는 중인 방향. 0 이면 밀어내는 중이 아니다. */
  const [flung, setFlung] = useState(0);

  const start = useRef<{ x: number; y: number; id: number } | null>(null);
  const moved = useRef(0);
  /** SLOP 을 넘겨 드래그로 확정됐는지. */
  const confirmed = useRef(false);
  /** 드래그로 넘긴 직후의 click 을 한 번 삼킨다. */
  const swallow = useRef(false);
  const timer = useRef<number | null>(null);

  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);

  const go = useCallback(
    (next: number) => {
      setOffset(0);
      setFlung(0);
      const clamped = Math.max(0, Math.min(count - 1, next));
      if (clamped === index) return;
      setFrom(clamped > index ? "next" : "prev");
      setIndex(clamped);
    },
    [count, index],
  );

  const step = useCallback((delta: number) => go(index + delta), [go, index]);

  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (event.button !== 0) return;
    start.current = { x: event.clientX, y: event.clientY, id: event.pointerId };
    moved.current = 0;
    confirmed.current = false;
  }, []);

  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const origin = start.current;
    if (!origin || event.pointerId !== origin.id) return;
    const mx = event.clientX - origin.x;
    const my = event.clientY - origin.y;
    if (!confirmed.current) {
      // 세로로 더 많이 움직였으면 페이지 스크롤에 양보한다
      if (Math.abs(mx) < SLOP || Math.abs(my) > Math.abs(mx)) return;
      confirmed.current = true;
      setDragging(true);
      setTouched(true);
      event.currentTarget.setPointerCapture(origin.id);
    }
    moved.current = mx;
    setOffset(mx);
  }, []);

  const finish = useCallback(
    (event: ReactPointerEvent<HTMLElement>) => {
      const origin = start.current;
      if (!origin || event.pointerId !== origin.id) return;
      if (event.currentTarget.hasPointerCapture(origin.id)) {
        event.currentTarget.releasePointerCapture(origin.id);
      }
      const distance = moved.current;
      const wasDrag = confirmed.current;
      start.current = null;
      confirmed.current = false;
      if (!wasDrag) return;
      setDragging(false);
      swallow.current = true;
      if (Math.abs(distance) < THRESHOLD) {
        setOffset(0);
        return;
      }
      const out = distance > 0 ? 1 : -1;
      setFlung(out);
      timer.current = window.setTimeout(() => step(out > 0 ? -1 : 1), FLING_MS);
    },
    [step],
  );

  const onClickCapture = useCallback(
    (event: { preventDefault: () => void; stopPropagation: () => void }) => {
      if (!swallow.current) return;
      swallow.current = false;
      event.preventDefault();
      event.stopPropagation();
    },
    [],
  );

  let cardStyle: CSSProperties = {};
  if (flung !== 0) {
    cardStyle = { transform: `translateX(${flung * 460}px) rotate(${flung * 9}deg)`, opacity: 0 };
  } else if (offset !== 0) {
    const fade = Math.min(Math.abs(offset) / 260, 0.45);
    cardStyle = {
      transform: `translateX(${offset}px) rotate(${(offset / 52).toFixed(2)}deg)`,
      opacity: 1 - fade,
    };
  }

  return {
    index,
    from,
    touched,
    dragging,
    cardStyle,
    go,
    step,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: finish,
      onPointerCancel: finish,
      onClickCapture,
    },
  };
}
