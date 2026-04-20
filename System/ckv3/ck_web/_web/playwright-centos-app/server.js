const express = require('express');
const app = express();
const port = 3000;

app.get('/', (req, res) => {
  res.send('Playwright Express Server is running on CentOS!');
});

app.listen(port, () => {
  console.log(`Server listening at http://localhost:${port}`);
  console.log('You can now add your Playwright logic to this file.');
});
