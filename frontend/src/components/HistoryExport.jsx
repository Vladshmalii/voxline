import { useEffect, useRef, useState } from 'react';
import styled from 'styled-components';
import { HiArrowDownTray, HiChevronDown } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { toast } from 'components/Toaster';
import { SecondaryButton } from 'components/ui';

const FORMATS = ['xlsx', 'csv'];

const Container = styled.div`
  position: relative;
`;

const Trigger = styled(SecondaryButton)`
  svg:last-child {
    transition: transform 180ms ease;
    transform: rotate(${({ $open }) => ($open ? '180deg' : '0deg')});
  }
  @media (prefers-reduced-motion: reduce) { svg:last-child { transition: none; } }
`;

// Same chrome as the user menu's dropdown (app/UserMenu.jsx).
const Menu = styled.div`
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 220px;
  padding: 6px;
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  z-index: 1000;
`;

const Item = styled.button`
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: transparent;
  color: ${({ theme }) => theme.colors.primary};
  font-size: 14px;
  text-align: left;
  cursor: pointer;
  small {
    display: block;
    margin-top: 2px;
    font-size: 12px;
    color: ${({ theme }) => theme.colors.secondary};
  }
  &:hover, &:focus-visible {
    outline: none;
    background: rgba(37, 99, 235, 0.08);
  }
`;

const pad = (n) => String(n).padStart(2, '0');

// The backend names the file itself; this only covers a cross-origin deploy
// that hides Content-Disposition from the browser.
const fallbackName = (name, format) => {
  const d = new Date();
  return `${name}_${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}_${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}.${format}`;
};

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on the next tick: some browsers start the download asynchronously.
  setTimeout(() => URL.revokeObjectURL(url), 0);
};

/**
 * "Export" button for a history page's filter header; the format is picked
 * from its menu.
 *
 * `onExport(format)` must send the page's own list query (same filters, same
 * sort, no limit/offset), so the file holds exactly what the list shows —
 * everything, when no filter is set. It resolves to `{ blob, filename }`
 * (smsApi.export / callsApi.export).
 */
export const HistoryExport = ({ name, onExport, disabled = false, empty = false }) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);
  const trigger = useRef(null);
  const firstItem = useRef(null);

  useEffect(() => {
    if (!open) return;
    firstItem.current?.focus();
    const onClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key !== 'Escape') return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = () => {
    if (empty) {
      toast(t('common.export.empty'), 'info');
      return;
    }
    setOpen((value) => !value);
  };

  const run = async (format) => {
    setOpen(false);
    setBusy(true);
    try {
      const { blob, filename } = await onExport(format);
      saveBlob(blob, filename || fallbackName(name, format));
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Container ref={ref}>
      <Trigger
        ref={trigger}
        theme={theme}
        type="button"
        $open={open}
        disabled={disabled || busy}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-busy={busy}
        title={t('common.export.title')}
        onClick={toggle}
      >
        <HiArrowDownTray />
        {busy ? t('common.export.busy') : t('common.export.button')}
        <HiChevronDown />
      </Trigger>
      {open && (
        <Menu theme={theme} role="menu">
          {FORMATS.map((format, index) => (
            <Item
              key={format}
              ref={index === 0 ? firstItem : undefined}
              theme={theme}
              type="button"
              role="menuitem"
              onClick={() => run(format)}
            >
              {t(`common.export.${format}`)}
              <small>{t(`common.export.${format}Hint`)}</small>
            </Item>
          ))}
        </Menu>
      )}
    </Container>
  );
};
