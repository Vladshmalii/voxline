// `npm run start:mock`: the mock backend plus the Vite dev server, one command.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const run = (cmd, args) => spawn(cmd, args, { cwd: root, stdio: 'inherit', shell: true });

const children = [
  run('node', ['mock/server.mjs']),
  run('npx', ['vite', '--mode', 'mock']),
];
const stop = () => children.forEach((c) => c.kill());
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
children.forEach((c) => c.on('exit', stop));
