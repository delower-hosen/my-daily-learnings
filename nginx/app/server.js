const express = require('express');
const app = express();
const PORT = 3000;
const os = require("os")
const hostname = os.hostname();

app.get("/", (req, res) => {
    res.send("Hello from " + hostname )
}) ;

app.get("/health", (req, res) => {
    res.status(200).send("OK");
});

app.listen(PORT, () => {
    console.log(`Server running on port ${PORT} on ${hostname}`);
});

