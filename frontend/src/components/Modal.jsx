import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import styled, { keyframes } from 'styled-components';
import { HiXMark } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';

const fade = keyframes`
  from { opacity: 0; }
  to { opacity: 1; }
`;

const rise = keyframes`
  from { opacity: 0; transform: translateY(8px) scale(0.985); }
  to { opacity: 1; transform: none; }
`;

const Overlay = styled.div`
  position: fixed;
  inset: 0;
  background: ${({ theme }) => (theme.mode === 'dark' ? 'rgba(2, 6, 14, 0.72)' : 'rgba(15, 23, 42, 0.42)')};
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5000;
  padding: 20px;
  animation: ${fade} 0.15s ease;
`;

const Panel = styled.div`
  width: 100%;
  max-width: ${({ $wide, $width }) => $width || ($wide ? '760px' : '520px')};
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.lg};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  overflow: hidden;
  animation: ${rise} 0.18s ease;
`;

const PanelHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 22px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.divider};
  flex-shrink: 0;
`;

const PanelTitle = styled.h3`
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  color: ${({ theme }) => theme.colors.primary};
`;

const CloseButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: none;
  border: none;
  border-radius: ${({ theme }) => theme.radii.sm};
  color: ${({ theme }) => theme.colors.muted};
  cursor: pointer;
  transition: color 0.12s ease, background 0.12s ease;

  &:hover {
    color: ${({ theme }) => theme.colors.primary};
    background: ${({ theme }) => theme.colors.hover};
  }
`;

const PanelBody = styled.div`
  padding: 20px 22px;
  overflow-y: auto;
  flex: 1;
`;

const PanelFooter = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 22px;
  border-top: 1px solid ${({ theme }) => theme.colors.divider};
  background: ${({ theme }) => theme.colors.surfaceAlt};
  flex-shrink: 0;
`;

export const Modal = ({ title, onClose, children, footer, wide = false, width }) => {
  const { theme } = useTheme();

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <Overlay theme={theme} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <Panel theme={theme} $wide={wide} $width={width} role="dialog" aria-modal="true" aria-label={title}>
        <PanelHeader theme={theme}>
          <PanelTitle theme={theme}>{title}</PanelTitle>
          <CloseButton theme={theme} type="button" onClick={onClose} aria-label="Close">
            <HiXMark size={18} />
          </CloseButton>
        </PanelHeader>
        <PanelBody>{children}</PanelBody>
        {footer && <PanelFooter theme={theme}>{footer}</PanelFooter>}
      </Panel>
    </Overlay>,
    document.body
  );
};
