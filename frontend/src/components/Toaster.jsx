import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import styled from 'styled-components';

// Dependency-free toaster: call toast('...', 'error') from any module, with a
// single <Toaster /> mounted once in App. Messages arrive already translated,
// so this component holds no text of its own.

let listener = null;
let nextId = 1;

export const toast = (message, type = 'info') => {
  if (listener) listener({ id: nextId++, message: String(message), type });
};

const Stack = styled.div`
  position: fixed;
  top: 72px;
  right: 20px;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: min(380px, calc(100vw - 32px));
`;

const COLORS = {
  info: '#2563EB',
  success: '#16A34A',
  error: '#DC2626',
};

const Item = styled.div`
  position: relative;
  padding: 12px 16px 12px 20px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  font-size: 13.5px;
  line-height: 1.45;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  cursor: pointer;
  word-break: break-word;

  &::before {
    content: '';
    position: absolute;
    left: 0;
    top: 8px;
    bottom: 8px;
    width: 4px;
    border-radius: 0 4px 4px 0;
    background: ${({ $type }) => COLORS[$type] || COLORS.info};
  }
`;

export const Toaster = () => {
  const [items, setItems] = useState([]);

  useEffect(() => {
    listener = (item) => {
      setItems((prev) => [...prev, item]);
      setTimeout(() => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
      }, 5000);
    };
    return () => {
      listener = null;
    };
  }, []);

  if (items.length === 0) return null;

  return createPortal(
    <Stack>
      {items.map((item) => (
        <Item
          key={item.id}
          $type={item.type}
          onClick={() => setItems((prev) => prev.filter((i) => i.id !== item.id))}
        >
          {item.message}
        </Item>
      ))}
    </Stack>,
    document.body
  );
};
