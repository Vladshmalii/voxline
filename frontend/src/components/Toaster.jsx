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
  top: 16px;
  right: 16px;
  z-index: 10000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: min(380px, calc(100vw - 32px));
`;

const COLORS = {
  info: '#2563eb',
  success: '#16a34a',
  error: '#dc2626',
};

const Item = styled.div`
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.4;
  color: #fff;
  background: ${({ $type }) => COLORS[$type] || COLORS.info};
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.2);
  cursor: pointer;
  word-break: break-word;
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
