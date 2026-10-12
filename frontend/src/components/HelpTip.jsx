import { useState, useRef, useLayoutEffect, useEffect } from 'react';
import { createPortal } from 'react-dom';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';

// A small circled "?" next to a field label. Click opens a popover with the
// field's description; click anywhere else (or Escape, or scrolling) closes
// it. The popover is position:fixed and rendered through a portal, so it
// overlays the page without affecting layout and cannot be clipped by a
// modal's overflow.

const POPOVER_MAX_WIDTH = 320;

const Trigger = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  margin-left: 6px;
  padding: 0;
  flex-shrink: 0;
  vertical-align: middle;
  border: 1px solid ${({ $open, theme }) => ($open ? theme.colors.accent : theme.colors.border)};
  border-radius: 50%;
  background: ${({ $open, theme }) => ($open ? theme.colors.accent : 'transparent')};
  color: ${({ $open, theme }) => ($open ? '#fff' : theme.colors.secondary)};
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  user-select: none;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.accent};
    color: ${({ $open, theme }) => ($open ? '#fff' : theme.colors.accent)};
  }
`;

const Popover = styled.div`
  position: fixed;
  z-index: 6000; /* above the modal overlay (5000) */
  padding: 10px 12px;
  font-size: 12.5px;
  font-weight: 400;
  line-height: 1.5;
  text-transform: none;
  letter-spacing: normal;
  white-space: pre-line;
  text-align: left;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 10px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.25);
`;

export const HelpTip = ({ text }) => {
  const { theme } = useTheme();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const triggerRef = useRef(null);
  const popoverRef = useRef(null);

  // Two-pass placement: render invisibly, measure, then pin below the icon —
  // or above it when the viewport bottom is closer than the popover is tall.
  useLayoutEffect(() => {
    if (!open) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const height = popoverRef.current?.offsetHeight ?? 0;
    const width = Math.min(POPOVER_MAX_WIDTH, window.innerWidth - 24);
    const left = Math.min(Math.max(12, rect.left - 8), window.innerWidth - width - 12);
    let top = rect.bottom + 6;
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - height - 6);
    }
    setPos({ top, left, width });
  }, [open, text]);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => {
      setPos(null);
      setOpen(false);
    };
    const onMouseDown = (e) => {
      if (triggerRef.current?.contains(e.target)) return;
      if (popoverRef.current?.contains(e.target)) return;
      close();
    };
    const onKey = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('keydown', onKey);
    // Fixed positioning drifts from the anchor when anything scrolls (the
    // modal body included) — closing is simpler and never wrong.
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  if (!text) return null;

  return (
    <>
      <Trigger
        ref={triggerRef}
        theme={theme}
        $open={open}
        type="button"
        aria-label="?"
        aria-expanded={open}
        // preventDefault keeps a click inside a <label> from toggling the
        // labelled control; stopPropagation keeps it out of row handlers.
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setPos(null);
          setOpen((v) => !v);
        }}
      >
        ?
      </Trigger>
      {open &&
        createPortal(
          <Popover
            ref={popoverRef}
            theme={theme}
            // The invisible first pass must already wear its final width, or
            // the measured height (and so the above/below flip) would be off.
            style={
              pos
                ? { top: pos.top, left: pos.left, maxWidth: pos.width }
                : {
                    visibility: 'hidden',
                    top: 0,
                    left: 0,
                    maxWidth: Math.min(POPOVER_MAX_WIDTH, window.innerWidth - 24),
                  }
            }
          >
            {text}
          </Popover>,
          document.body
        )}
    </>
  );
};
