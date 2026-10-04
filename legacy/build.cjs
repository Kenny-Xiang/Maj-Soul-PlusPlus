const fs = require('node:fs');
const path = require('node:path');
const core = fs.readFileSync(path.join(__dirname, '../src/core.cjs'), 'utf8');
const browser = fs.readFileSync(path.join(__dirname, '../src/browser.js'), 'utf8');
const bundle = `(function(discover) {\n'use strict';\nconst core = (() => { const module = {exports:{}};\n${core}\nreturn module.exports; })();\n${browser}\n})(typeof queryInstances === 'function' ? queryInstances : null);\n`;
fs.writeFileSync(path.join(__dirname, '安装终端监听.js'), bundle);
console.log('Generated 安装终端监听.js');
