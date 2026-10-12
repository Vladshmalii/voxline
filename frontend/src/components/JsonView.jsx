import { useState } from 'react';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';

// Syntax-highlighted, collapsible JSON tree. Keys, strings, numbers, booleans
// and null each get their own colour (a GitHub-ish palette that reads on both
// the light and the dark background), objects/arrays fold away, and the whole
// blob can be copied. Props stay `value` + `maxHeight` so callers are unchanged.

const SYNTAX = {
  light: { key: '#0550ae', string: '#0a7d33', number: '#953800', boolean: '#8250df', null: '#6b6b6b' },
  dark: { key: '#79c0ff', string: '#7ee787', number: '#ffa657', boolean: '#d2a8ff', null: '#8b949e' },
};

const Root = styled.div`
  position: relative;
  font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
  font-size: 12.5px;
  line-height: 1.65;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 10px;
  padding: 12px 14px;
  overflow: auto;
  max-height: ${({ $maxHeight }) => $maxHeight || '360px'};

  &::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }
  &::-webkit-scrollbar-thumb {
    background: ${({ theme }) => theme.colors.border};
    border-radius: 4px;
  }
`;

const Line = styled.div`
  display: flex;
  align-items: flex-start;
  white-space: pre-wrap;
  word-break: break-word;
`;

const Caret = styled.button`
  flex-shrink: 0;
  width: 14px;
  margin-right: 2px;
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
  color: ${({ theme }) => theme.colors.secondary};
  font: inherit;
  line-height: inherit;
  text-align: left;
  user-select: none;
`;

const Indent = styled.span`
  flex-shrink: 0;
  display: inline-block;
  width: 14px;
`;

const Children = styled.div`
  padding-left: 10px;
  margin-left: 6px;
  border-left: 1px dashed ${({ theme }) => theme.colors.border};
`;

const Punct = styled.span`
  color: ${({ theme }) => theme.colors.secondary};
`;

const CopyButton = styled.button`
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 3px 9px;
  font-size: 11px;
  font-family: inherit;
  color: ${({ theme }) => theme.colors.secondary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 6px;
  cursor: pointer;
  opacity: 0.85;

  &:hover {
    opacity: 1;
    border-color: ${({ theme }) => theme.colors.secondary};
  }
`;

const Leaf = ({ value, colors }) => {
  if (value === null) return <span style={{ color: colors.null }}>null</span>;
  const type = typeof value;
  if (type === 'string') return <span style={{ color: colors.string }}>&quot;{value}&quot;</span>;
  if (type === 'number' || type === 'boolean')
    return <span style={{ color: colors[type] }}>{String(value)}</span>;
  return <span>{String(value)}</span>;
};

// One line of the tree. `name` is the object key / array index (undefined at the
// root); `trailComma` draws the separating comma between siblings.
const Node = ({ name, value, depth, isArrayItem, trailComma, theme, colors }) => {
  const collapsible = value !== null && typeof value === 'object';
  const [open, setOpen] = useState(depth < 2); // first two levels start expanded

  const label =
    name === undefined ? null : (
      <>
        <span style={{ color: isArrayItem ? theme.colors.muted : colors.key }}>{name}</span>
        <Punct theme={theme}>: </Punct>
      </>
    );

  if (!collapsible) {
    return (
      <Line>
        <Indent />
        {label}
        <span>
          <Leaf value={value} colors={colors} />
          {trailComma && <Punct theme={theme}>,</Punct>}
        </span>
      </Line>
    );
  }

  const isArray = Array.isArray(value);
  const entries = isArray ? value.map((v, i) => [i, v]) : Object.entries(value);
  const [openBr, closeBr] = isArray ? ['[', ']'] : ['{', '}'];

  if (entries.length === 0) {
    return (
      <Line>
        <Indent />
        {label}
        <span>
          <Punct theme={theme}>
            {openBr}
            {closeBr}
          </Punct>
          {trailComma && <Punct theme={theme}>,</Punct>}
        </span>
      </Line>
    );
  }

  return (
    <div>
      <Line>
        <Caret theme={theme} type="button" onClick={() => setOpen((o) => !o)}>
          {open ? '▾' : '▸'}
        </Caret>
        {label}
        <span>
          <Punct theme={theme}>{openBr}</Punct>
          {!open && (
            <Punct theme={theme}>
              {' … '}
              {closeBr}
              {trailComma && ','} <span style={{ opacity: 0.7 }}>{entries.length}</span>
            </Punct>
          )}
        </span>
      </Line>
      {open && (
        <Children theme={theme}>
          {entries.map(([k, v], i) => (
            <Node
              key={k}
              name={k}
              value={v}
              depth={depth + 1}
              isArrayItem={isArray}
              trailComma={i < entries.length - 1}
              theme={theme}
              colors={colors}
            />
          ))}
        </Children>
      )}
      {open && (
        <Line>
          <Indent />
          <Punct theme={theme}>
            {closeBr}
            {trailComma && ','}
          </Punct>
        </Line>
      )}
    </div>
  );
};

export const JsonView = ({ value, maxHeight }) => {
  const { theme } = useTheme();
  const [copied, setCopied] = useState(false);
  const colors = SYNTAX[theme.mode] || SYNTAX.light;

  // A plain string (or anything non-object) is shown as a lone leaf.
  const isTree = value !== null && typeof value === 'object';

  const copy = () => {
    let text;
    try {
      text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    } catch (_) {
      text = String(value);
    }
    navigator.clipboard?.writeText(text ?? '').then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      },
      () => undefined
    );
  };

  return (
    <Root theme={theme} $maxHeight={maxHeight}>
      <CopyButton theme={theme} type="button" onClick={copy}>
        {copied ? '✓' : 'copy'}
      </CopyButton>
      {isTree ? (
        <Node value={value} depth={0} theme={theme} colors={colors} />
      ) : (
        <Line>
          <Leaf value={value} colors={colors} />
        </Line>
      )}
    </Root>
  );
};
