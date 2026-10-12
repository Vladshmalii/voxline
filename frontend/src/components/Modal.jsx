import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import styled from 'styled-components';
import { HiXMark } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';

const Overlay = styled.div`
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 5000;
  padding: 20px;
`;

const Panel = styled.div`
  width: 100%;
  max-width: ${({ $wide, $width }) => $width || ($wide ? '760px' : '520px')};
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 16px;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.3);
  overflow: hidden;
`;

const PanelHeader = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  flex-shrink: 0;
`;

const PanelTitle = styled.h3`
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
`;

const CloseButton = styled.button`
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  background: none;
  border: none;
  border-radius: 6px;
  color: ${({ theme }) => theme.colors.secondary};
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;

  &:hover {
    color: ${({ theme }) => theme.colors.primary};
    background: ${({ theme }) => theme.colors.hover};
  }
`;

const PanelBody = styled.div`
  padding: 18px 20px;
  overflow-y: auto;
  flex: 1;
`;

const PanelFooter = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid ${({ theme }) => theme.colors.border};
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
    <Overlay onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <Panel theme={theme} $wide={wide} $width={width}>
        <PanelHeader theme={theme}>
          <PanelTitle theme={theme}>{title}</PanelTitle>
          <CloseButton theme={theme} type="button" onClick={onClose}>
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
