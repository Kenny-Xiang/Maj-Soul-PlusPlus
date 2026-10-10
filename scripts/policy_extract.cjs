#!/usr/bin/env node
const fs = require('node:fs');
const {extractGame} = require('../src/policy_replay.cjs');

function main(argv) {
  const input = argv[0], outputIndex = argv.indexOf('--output'), auditIndex = argv.indexOf('--audit');
  if (!input || outputIndex < 0 || auditIndex < 0 || !argv[outputIndex + 1] || !argv[auditIndex + 1]) {
    throw new Error('Usage: node scripts/policy_extract.cjs decoded.json --output samples.jsonl --audit audit.json');
  }
  const {samples, audit} = extractGame(JSON.parse(fs.readFileSync(input, 'utf8')));
  fs.writeFileSync(argv[outputIndex + 1], samples.map(sample => JSON.stringify(sample)).join('\n') + (samples.length ? '\n' : ''));
  fs.writeFileSync(argv[auditIndex + 1], JSON.stringify(audit, null, 2) + '\n');
  process.stdout.write(JSON.stringify(audit) + '\n');
}

if (require.main === module) {
  try {main(process.argv.slice(2));}
  catch (error) {process.stderr.write(error.message + '\n'); process.exitCode = 1;}
}
module.exports = {main};
