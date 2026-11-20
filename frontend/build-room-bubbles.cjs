const {readFileSync} = require('node:fs');
const {dirname, join} = require('node:path');
const {buildSync} = require('esbuild');

const licenses = ['react-bubble-ui', 'react', 'react-dom', 'scheduler', 'object-assign'].map(name => {
  const folder = dirname(require.resolve(name + '/package.json'));
  const file = name === 'object-assign' ? 'license' : 'LICENSE';
  return name + '\n' + readFileSync(join(folder, file), 'utf8').trim();
});

buildSync({
  entryPoints: [join(__dirname, 'room-bubbles.jsx')],
  outfile: join(__dirname, '../public/room-bubbles.js'),
  bundle: true,
  minify: true,
  target: ['es2020', 'safari14'],
  define: {'process.env.NODE_ENV': '"production"'},
  banner: {js: '/*! Third-party licenses\n' + licenses.join('\n\n').replaceAll('*/', '* /') + '\n*/'},
  legalComments: 'inline'
});
