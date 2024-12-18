const SCALE = 1;
var backgroundImage = null;
var explosionImage = null;
var laserImage = null;
var hullImage = null;
var turretImage = null;
var galaxyImage = null;
var exhaustImages = null;
var arena = null;
var lastUpdate = null;
var webSocket = null;
var stars = [];
var leaderboardUpdated = false;
var awidth = 1500;
var aheight = 1000;

function getArenaId() {
    var loc = window.location;
    const prefix = "/game/";
    var arenaId = "0";

    if (loc.pathname.startsWith(prefix)) {
        arenaId = loc.pathname.slice(prefix.length);
    }
    return arenaId;
}

async function updateLeaderboard() {
    var leaderboardBody = document.getElementById("leaderboardBody");
    if (leaderboardUpdated) {
        return;
    }
    let loc = window.location;
    let arenaId = getArenaId();
    let leaderboardUrl = `${loc.protocol}//${loc.host}/api/leaderboard/${arenaId}`
    let response = await fetch(leaderboardUrl);
    let leaderboardData = await response.json();
    console.log(leaderboardData);

    while (leaderboardBody.hasChildNodes()) {
        leaderboardBody.removeChild(leaderboardBody.lastChild);
    }

    _.forEach(leaderboardData, (data, position) => {
        console.log(data, position);
        let tdRow = document.createElement("tr");
        leaderboardBody.appendChild(tdRow);
        let tdPos = document.createElement("td");
        tdPos.innerText = position + 1;
        tdRow.appendChild(tdPos);
        _.map(data, d => {
            let tdD = document.createElement("td");
            tdD.innerText = d;
            tdRow.appendChild(tdD);
        });
    });
    leaderboardUpdated = true;
}

function openSocket() {
    var loc = window.location;
    var scheme = loc.protocol === "https:" ? "wss:" : "ws:";
    var arenaId = getArenaId();

    document.title = `Battlefield Arena ${arenaId}`

    webSocket = new WebSocket(`${scheme}//${loc.host}/api/watch/${arenaId}`);

    webSocket.onopen = function (event) {
        console.log("open websocket")
    };

    webSocket.onmessage = function (event) {
        arena = transpose(JSON.parse(event.data));
        window.requestAnimationFrame(draw);
    };

    webSocket.onclose = function (event) {
        window.setTimeout(openSocket, 1000);
    };
}

const transpose = function (obj) {
    if (_.isNumber(obj) || _.isString(obj) || _.isNull(obj) || _.isBoolean(obj)) {
        return obj;
    }
    if (_.isArray(obj)) {
        return _.map(obj, transpose);
    }
    if (obj._t) {
        delete obj._t;
        const keys = _.keys(obj);
        const values = _.values(obj).map(transpose);
        return _.zip(...values).map(v => _.zipObject(keys, v));
    }
    return _.mapValues(obj, transpose);
}

window.onload = function () {
    let battlefieldHeader = document.getElementById("battlefieldHeader");
    battlefieldHeader.innerText = `Battlefield #${getArenaId()}`;
    laserImage = document.getElementById("laser");
    hullImage = document.getElementById("ship");
    turretImage = document.getElementById("turret");
    explosionImage = document.getElementById("explosion");
    galaxyImage = document.getElementById("galaxy");
    backgroundImage = document.getElementById("background");
    exhaustImages = [
        document.getElementById("exhaust0"),
        document.getElementById("exhaust1"),
        document.getElementById("exhaust0"),
        document.getElementById("exhaust1"),
        document.getElementById("exhaust0"),
        document.getElementById("exhaust1")
    ];
    openSocket();
    for (var i=0; i<2000; i++) {
        stars.push(randomStar());
    }
    updateLeaderboard();
}

function randomStar() {
    return {x: 4*Math.random() - 2, y: 4*Math.random() - 2, z: 10*Math.random()};
}

function draw(timestamp) {
    if (timestamp == lastUpdate) {
        return;
    }
    lastUpdate = timestamp;

    const ctx = document.getElementById('canvas').getContext('2d');

    ctx.save();
    ctx.clearRect(0, 0, awidth, aheight);
    ctx.strokeStyle = 'black';
    ctx.fillStyle = 'black';
    ctx.fillRect(0, 0, awidth, aheight);
    ctx.stroke();
    ctx.globalAlpha = 0.3;
    ctx.drawImage(backgroundImage, 0, 0, backgroundImage.width / 2, backgroundImage.height / 2, 0, 0, awidth, aheight);
    ctx.restore();

    ctx.save();
    ctx.translate(500, 500);

    if (!arena.winner) {
        ctx.save();
        const galaxyScale = 100 / Math.max(1, arena.remaining);
        ctx.scale(galaxyScale, galaxyScale);
        ctx.drawImage(galaxyImage, -galaxyImage.width / 2, -galaxyImage.height / 2);
        ctx.restore();
        leaderboardUpdated = false;
    }

    ctx.fillStyle = `white`;
    stars.forEach(star => {
        const size = (2 - star.z/10)/(awidth*aheight/2.0);
        ctx.save();
        ctx.globalAlpha = (10-star.z) / 10;
        ctx.scale(awidth, aheight);
        ctx.fillRect(star.x / star.z, star.y / star.z, size, size);
        ctx.restore();
        star.z -= 0.01;
    });
    stars = stars.map((s) => s.z > 0 ? s : randomStar())
    ctx.restore();

    arena.robots.forEach(robot => {
        const img = hullImage;
        const dx = robot.position.x;
        const dy = robot.position.y;

        ctx.save();
        ctx.translate(dx, dy);
        ctx.scale(SCALE, SCALE);

        // Dead robots become ghosts
        if (robot.health <= 0) {
            ctx.globalAlpha = 0.5;
        }

        // Labels
        const labely = hullImage.height * (dy < 500 ? 0.75 : -0.75);
        ctx.fillStyle = 'red';
        ctx.font = '16px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`${robot.name} (${robot.health}%)`, 0, labely);

        // Draw the hull
        ctx.rotate(Math.PI / 2 + robot.hull_angle / 180 * Math.PI);
        ctx.drawImage(img, -img.width / 2, -img.height / 2);
        if (robot.accelerate_progress) {
            const exhaustImg = exhaustImages[robot.accelerate_progress];
            ctx.drawImage(exhaustImg, -exhaustImg.width / 2, img.height / 2 - exhaustImg.height / 2);
        }

        // Draw the turret
        const imgDim = turretImage.height;
        const idx = robot.firing_progress || 0;
        ctx.rotate(robot.turret_angle / 180 * Math.PI);
        ctx.drawImage(turretImage, imgDim*idx, 0, imgDim, imgDim, -imgDim / 2, -imgDim / 2, imgDim, imgDim);
        // ctx.drawImage(turretImage, -turretImage.width / 2, -turretImage.height / 2);
        ctx.restore();
    });

    arena.missiles.forEach(missile => {
        const laserScale = SCALE * (0.1 + 0.9 * missile.energy / 5);
        if (!missile.exploding) {
            const img = laserImage;
            const imgDim = laserImage.height;
            const idx = Math.round(timestamp*.02) % (img.width / imgDim);
            const dx = missile.position.x;
            const dy = missile.position.y;

            ctx.save();
            ctx.translate(dx, dy);
            ctx.scale(laserScale, laserScale)
            ctx.rotate(Math.PI / 2 + missile.angle / 180 * Math.PI);
            ctx.drawImage(img, imgDim*idx, 0, imgDim, imgDim, -imgDim / 2, -imgDim / 2, imgDim, imgDim);
            ctx.restore();

        } else {
            const img = explosionImage;
            const imgDim = explosionImage.height;
            const idx = missile.explode_progress;
            const dx = missile.position.x
            const dy = missile.position.y
            ctx.save();
            ctx.translate(dx, dy);
            ctx.scale(laserScale * 2, laserScale * 2)
            ctx.drawImage(img, imgDim*idx, 0, imgDim, imgDim, -imgDim / 2, -imgDim / 2, imgDim, imgDim);
            ctx.restore();
        }
    });

    if (arena.robots.length === 0) {
        ctx.fillStyle = 'red';
        ctx.font = '64px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`Waiting for players`, 500, 500);
        window.requestAnimationFrame(draw);
    }

    if (arena.winner) {
        ctx.fillStyle = 'red';
        ctx.font = '64px monospace';
        ctx.textAlign = 'center';
        ctx.fillText(`Winner ${arena.winner}!`, 500, 500);
        if (!leaderboardUpdated) {
            updateLeaderboard();
        }
        window.requestAnimationFrame(draw);
    }
}
