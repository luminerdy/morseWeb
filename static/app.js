function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

let practiceCheckTimer = null;
let lastCheckedPracticeMorse = "";
let pendingPracticeMorse = "";
let practiceActive = true;
let practiceBusy = false;
let keyboardKeyerActive = true;
let keyboardPressStartedAt = null;
let keyboardLastReleasedAt = null;
let keyboardMorse = "";
let keyboardTimingEvents = [];
let keyboardAudioCtx = null;
let keyboardToneOscillator = null;
let keyboardToneGain = null;
let practiceAudioPlaying = false;
let browserAudioCtx = null;
let browserPlayback = null;
let wordCheckTimer = null;
let lastCheckedWordMorse = "";
let pendingWordMorse = "";
let wordStartedAt = null;
let wordAutoAdvanceTimer = null;

const KEYBOARD_DASH_THRESHOLD_UNITS = 2.5;
const MORSE_DECODE = {
    ".": "E",
    "-": "T",
    ".-": "A",
    "-.": "N",
    "..": "I",
    "--": "M",
    "-...": "B",
    "-.-.": "C",
    "-..": "D",
    "..-.": "F",
    "--.": "G",
    "....": "H",
    ".---": "J",
    "-.-": "K",
    ".-..": "L",
    "---": "O",
    ".--.": "P",
    "--.-": "Q",
    ".-.": "R",
    "...": "S",
    "..-": "U",
    "...-": "V",
    ".--": "W",
    "-..-": "X",
    "-.--": "Y",
    "--..": "Z",
    ".----": "1",
    "..---": "2",
    "...--": "3",
    "....-": "4",
    ".....": "5",
    "-....": "6",
    "--...": "7",
    "---..": "8",
    "----.": "9",
    "-----": "0"
};

function ensureBrowserAudioContext() {
    if (!browserAudioCtx) {
        browserAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }

    if (browserAudioCtx.state === "suspended") {
        browserAudioCtx.resume();
    }

    return browserAudioCtx;
}

function getMorseTiming() {
    const source = document.body ? document.body.dataset : {};
    const numberFromData = (name, fallback) => {
        const parsed = Number(source[name]);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
    };

    return {
        toneHz: numberFromData("toneHz", 700),
        dotMs: numberFromData("dotMs", 80),
        dashMs: numberFromData("dashMs", 240),
        symbolGapMs: numberFromData("symbolGapMs", 80),
        letterGapMs: numberFromData("letterGapMs", 514),
        wordGapMs: numberFromData("wordGapMs", 1200),
        inputDashThresholdMs: numberFromData("inputDashThresholdMs", 200)
    };
}

function getKeyboardDashThresholdMs() {
    const timing = getMorseTiming();
    return timing.inputDashThresholdMs || Math.round(timing.dotMs * KEYBOARD_DASH_THRESHOLD_UNITS);
}

function updateMorseTimingData(timing) {
    if (!timing || !document.body) {
        return;
    }

    const fields = {
        toneHz: "tone_hz",
        dotMs: "dot_ms",
        dashMs: "dash_ms",
        symbolGapMs: "symbol_gap_ms",
        letterGapMs: "letter_gap_ms",
        wordGapMs: "word_gap_ms",
        inputDashThresholdMs: "input_dash_threshold_ms"
    };

    for (const [dataKey, timingKey] of Object.entries(fields)) {
        if (timing[timingKey] !== undefined) {
            document.body.dataset[dataKey] = timing[timingKey];
        }
    }
}

async function browserBeep(audioCtx, durationMs, playback = null) {
    if (audioCtx.state === "suspended") {
        await audioCtx.resume();
    }

    const oscillator = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    oscillator.frequency.value = getMorseTiming().toneHz;
    oscillator.type = "sine";
    gain.gain.value = 0.2;

    oscillator.connect(gain);
    gain.connect(audioCtx.destination);

    if (playback) {
        playback.oscillator = oscillator;
    }

    oscillator.start();
    await sleep(durationMs);

    try {
        oscillator.stop();
    } catch (error) {
        // The stop button may have already stopped this oscillator.
    }

    if (playback && playback.oscillator === oscillator) {
        playback.oscillator = null;
    }
}

async function triggerDailyCelebration() {
    const audioCtx = ensureBrowserAudioContext();

    try {
        await playMorseText("...-");
    } finally {
        await releaseBrowserAudioContext();
    }
}

function initializeDailyMissionReward() {
    const daily = document.querySelector("[data-daily-complete]");

    if (!daily || daily.dataset.dailyComplete !== "true") {
        return;
    }

    const rewardKey = [
        "dailyMissionReward",
        daily.dataset.dailyDate || "",
        daily.dataset.dailyStudent || ""
    ].join(":");

    if (window.localStorage.getItem(rewardKey)) {
        return;
    }

    window.localStorage.setItem(rewardKey, "played");

    setTimeout(() => {
        triggerDailyCelebration();
    }, 500);
}

function ensureKeyboardAudioContext() {
    keyboardAudioCtx = ensureBrowserAudioContext();
    return keyboardAudioCtx;
}

async function testBrowserSound() {
    await resetSoundState();

    const audioCtx = ensureBrowserAudioContext();

    try {
        await browserBeep(audioCtx, 120);
    } finally {
        await releaseBrowserAudioContext();
    }
}

async function resetSoundState() {
    stopBrowserPlayback();
    stopKeyboardTone();
    practiceAudioPlaying = false;

    await releaseBrowserAudioContext();
}

async function releaseBrowserAudioContext() {
    if (browserAudioCtx && browserAudioCtx.state !== "closed") {
        try {
            await browserAudioCtx.close();
        } catch (error) {
            console.log("Unable to close browser audio context", error);
        }
    }

    browserAudioCtx = null;
    keyboardAudioCtx = null;
}

function setHomePlaybackState(isPlaying) {
    const playButton = document.getElementById("playHereButton");
    const stopButton = document.getElementById("stopHereButton");

    if (playButton) {
        playButton.disabled = isPlaying;
    }

    if (stopButton) {
        stopButton.disabled = !isPlaying;
    }
}

function startKeyboardTone() {
    if (keyboardToneOscillator) {
        return;
    }

    const audioCtx = ensureKeyboardAudioContext();
    const oscillator = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    oscillator.frequency.value = getMorseTiming().toneHz;
    oscillator.type = "sine";
    gain.gain.value = 0.2;

    oscillator.connect(gain);
    gain.connect(audioCtx.destination);
    oscillator.start();

    keyboardToneOscillator = oscillator;
    keyboardToneGain = gain;
}

function stopKeyboardTone() {
    if (!keyboardToneOscillator) {
        return;
    }

    keyboardToneOscillator.stop();
    keyboardToneOscillator.disconnect();

    if (keyboardToneGain) {
        keyboardToneGain.disconnect();
    }

    keyboardToneOscillator = null;
    keyboardToneGain = null;
}

async function playMorseText(morseText, playback = null) {
    if (!morseText) {
        return;
    }

    const audioCtx = ensureBrowserAudioContext();
    const timing = getMorseTiming();

    for (const ch of morseText) {
        if (playback && playback.cancelled) {
            return;
        }

        if (ch === ".") {
            await browserBeep(audioCtx, timing.dotMs, playback);
            await sleep(timing.symbolGapMs);
        } else if (ch === "-") {
            await browserBeep(audioCtx, timing.dashMs, playback);
            await sleep(timing.symbolGapMs);
        } else if (ch === " ") {
            await sleep(timing.letterGapMs);
        } else if (ch === "/") {
            await sleep(timing.wordGapMs);
        }
    }
}

async function playInBrowser() {
    const morseBox = document.getElementById("morseBox");

    if (!morseBox) {
        return;
    }

    const morseText = morseBox.innerText.trim();

    if (!morseText || morseText === "Type a message above.") {
        return;
    }

    stopBrowserPlayback();

    const playback = {
        cancelled: false,
        oscillator: null
    };

    browserPlayback = playback;
    setHomePlaybackState(true);

    try {
        await playMorseText(morseText, playback);
    } finally {
        if (browserPlayback === playback) {
            browserPlayback = null;
            setHomePlaybackState(false);
        }
    }
}

async function playWordCard() {
    const panel = document.querySelector("[data-word-morse]");

    if (!panel) {
        return;
    }

    const morseText = (panel.dataset.wordMorse || "").trim();

    if (!morseText) {
        return;
    }

    await stopWordPlayback();

    const playback = {
        cancelled: false,
        oscillator: null
    };

    browserPlayback = playback;

    try {
        await playMorseText(morseText, playback);
    } finally {
        if (browserPlayback === playback) {
            browserPlayback = null;
        }
    }
}

async function stopWordPlayback() {
    stopBrowserPlayback();
    cancelWordAutoAdvance();
}

function cancelWordAutoAdvance() {
    if (wordAutoAdvanceTimer) {
        clearTimeout(wordAutoAdvanceTimer);
    }

    wordAutoAdvanceTimer = null;
}

async function initializeWordPractice() {
    const panel = getWordPanel();

    if (!panel) {
        return;
    }

    await clearKeyInput();

    const params = new URLSearchParams(window.location.search);

    if (params.get("autoplay") === "1") {
        setTimeout(playWordCard, 300);
    }
}

function stopBrowserPlayback() {
    if (!browserPlayback) {
        setHomePlaybackState(false);
        return;
    }

    browserPlayback.cancelled = true;

    if (browserPlayback.oscillator) {
        try {
            browserPlayback.oscillator.stop();
        } catch (error) {
            // Already stopped.
        }
    }

    browserPlayback = null;
    setHomePlaybackState(false);
}

async function playPracticePromptInBrowser() {
    const panel = getPracticePanel();

    if (!panel || practiceAudioPlaying) {
        return;
    }

    practiceAudioPlaying = true;

    try {
        await playMorseText(panel.dataset.expectedMorse || "");
    } finally {
        practiceAudioPlaying = false;
        await releaseBrowserAudioContext();
    }
}

async function updateLiveKey() {
    const liveMorse = document.getElementById("liveMorse");
    const liveDecoded = document.getElementById("liveDecoded");

    if (!liveMorse || !liveDecoded) {
        return;
    }

    if (keyboardKeyerActive) {
        return;
    }
}

async function clearKeyInput() {
    resetVirtualKeyer();
    resetPracticeAutoCheck();
}

function getPracticePanel() {
    return document.querySelector("[data-practice-target][data-expected-morse]");
}

function getWordPanel() {
    return document.querySelector("[data-word-target][data-word-morse]");
}

function getBonusConfig() {
    const panel = getPracticePanel();

    if (!panel || !panel.dataset.bonusKind) {
        return null;
    }

    return {
        kind: panel.dataset.bonusKind,
        sessionId: panel.dataset.bonusSession || "",
        goal: Number(panel.dataset.bonusGoal) || 20
    };
}

function getPracticeMode() {
    const panel = getPracticePanel();
    return panel ? (panel.dataset.practiceMode || "send") : "send";
}

function normalizeMorse(value) {
    return value.trim().replace(/\s+/g, " ");
}

function countMorseSymbols(value) {
    return value.replace(/[\s/]/g, "").length;
}

function setPracticeFeedback(message) {
    const feedback = document.getElementById("practiceFeedback");

    if (!feedback) {
        return;
    }

    feedback.innerText = message;
    feedback.hidden = !message;

    feedback.classList.remove("success", "needs-practice");

    if (message.startsWith("Correct")) {
        feedback.classList.add("success");
    } else if (message.startsWith("Try")) {
        feedback.classList.add("needs-practice");
    }
}

function setWordFeedback(message) {
    const feedback = document.getElementById("wordFeedback");

    if (!feedback) {
        return;
    }

    feedback.innerText = message;
    feedback.hidden = !message;
    feedback.classList.remove("success", "needs-practice");

    if (message.startsWith("Correct")) {
        feedback.classList.add("success");
    } else if (message.startsWith("Try")) {
        feedback.classList.add("needs-practice");
    }
}

function resetPracticeAutoCheck() {
    if (practiceCheckTimer) {
        clearTimeout(practiceCheckTimer);
    }

    practiceCheckTimer = null;
    lastCheckedPracticeMorse = "";
    pendingPracticeMorse = "";
    setPracticeFeedback("");
    resetWordAutoCheck();
}

function resetWordAutoCheck() {
    if (wordCheckTimer) {
        clearTimeout(wordCheckTimer);
    }

    cancelWordAutoAdvance();
    wordCheckTimer = null;
    lastCheckedWordMorse = "";
    pendingWordMorse = "";
    wordStartedAt = null;
    setWordFeedback("");
}

function scheduleWordAutoCheck(rawMorse, decoded = "") {
    const panel = getWordPanel();

    if (!panel) {
        return;
    }

    const actualMorse = normalizeMorse(rawMorse);
    const expectedMorse = normalizeMorse(panel.dataset.wordMorse || "");

    if (!actualMorse) {
        resetWordAutoCheck();
        return;
    }

    if (wordStartedAt === null) {
        wordStartedAt = performance.now();
    }

    if (actualMorse === lastCheckedWordMorse) {
        return;
    }

    if (countMorseSymbols(actualMorse) < countMorseSymbols(expectedMorse)) {
        if (wordCheckTimer) {
            clearTimeout(wordCheckTimer);
            wordCheckTimer = null;
        }
        pendingWordMorse = "";
        return;
    }

    if (actualMorse === pendingWordMorse) {
        return;
    }

    if (wordCheckTimer) {
        clearTimeout(wordCheckTimer);
    }

    pendingWordMorse = actualMorse;
    wordCheckTimer = setTimeout(() => {
        checkWordAnswer(actualMorse, expectedMorse, panel.dataset.wordTarget || "", decoded);
    }, 1300);
}

function checkWordAnswer(actualMorse, expectedMorse, target, decoded = "") {
    lastCheckedWordMorse = actualMorse;
    pendingWordMorse = "";
    const correct = actualMorse === expectedMorse;
    const elapsedMs = wordStartedAt === null ? null : Math.round(performance.now() - wordStartedAt);

    recordWordResult(target, correct, actualMorse, expectedMorse, decoded, elapsedMs);

    if (correct) {
        setWordFeedback(`Correct: ${target}.`);
        rewardCorrectWord();
        scheduleWordAutoAdvance();
        return;
    }

    const heard = decoded ? ` I read ${decoded}.` : "";
    setWordFeedback(`Not yet. Tap Clear, then try ${target} again. ${target} is ${expectedMorse}. I heard ${actualMorse}.${heard}`);
}

async function recordWordResult(target, correct, actualMorse, expectedMorse, decoded, elapsedMs) {
    try {
        await fetch("/words/result", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                word: target,
                correct,
                actual_morse: actualMorse,
                expected_morse: expectedMorse,
                decoded,
                elapsed_ms: elapsedMs,
                timing_events: keyboardKeyerActive ? keyboardTimingEvents : []
            })
        });
    } catch (error) {
        console.log("Unable to record word result", error);
    }
}

function rewardCorrectWord() {
    const panel = getWordPanel();

    if (panel) {
        panel.classList.remove("word-correct-reward");
        void panel.offsetWidth;
        panel.classList.add("word-correct-reward");
        setTimeout(() => {
            panel.classList.remove("word-correct-reward");
        }, 2200);
    }
}

function scheduleWordAutoAdvance() {
    const nextLink = document.querySelector("[data-word-next]");

    if (!nextLink) {
        return;
    }

    cancelWordAutoAdvance();
    wordAutoAdvanceTimer = setTimeout(() => {
        window.location.href = nextLink.href;
    }, 2000);
}

function schedulePracticeAutoCheck(rawMorse) {
    const panel = getPracticePanel();

    if (!panel || !["send", "echo", "learn"].includes(getPracticeMode()) || !practiceActive || practiceBusy) {
        return;
    }

    const actualMorse = normalizeMorse(rawMorse);
    const expectedMorse = normalizeMorse(panel.dataset.expectedMorse || "");

    if (!actualMorse) {
        if (practiceCheckTimer) {
            clearTimeout(practiceCheckTimer);
            practiceCheckTimer = null;
        }
        lastCheckedPracticeMorse = "";
        pendingPracticeMorse = "";
        return;
    }

    if (actualMorse === lastCheckedPracticeMorse) {
        return;
    }

    if (countMorseSymbols(actualMorse) < countMorseSymbols(expectedMorse)) {
        if (practiceCheckTimer) {
            clearTimeout(practiceCheckTimer);
            practiceCheckTimer = null;
        }
        pendingPracticeMorse = "";
        return;
    }

    if (actualMorse === pendingPracticeMorse) {
        return;
    }

    if (practiceCheckTimer) {
        clearTimeout(practiceCheckTimer);
    }

    pendingPracticeMorse = actualMorse;
    practiceCheckTimer = setTimeout(() => {
        checkPracticeAnswer(actualMorse, expectedMorse, panel.dataset.practiceTarget || "");
    }, 1100);
}

function checkPracticeAnswer(actualMorse, expectedMorse, target) {
    lastCheckedPracticeMorse = actualMorse;
    pendingPracticeMorse = "";
    practiceBusy = true;

    const bonus = getBonusConfig();
    if (bonus) {
        const correct = actualMorse === expectedMorse;
        setPracticeFeedback(correct
            ? `Correct: ${target}.`
            : `${target} is ${expectedMorse}. I heard ${actualMorse}.`
        );
        recordPracticeResult(target, correct).then(data => {
            const summary = data ? data.bonus : null;
            updateBonusScore(summary);
            if (summary && summary.complete) {
                setPracticeFeedback(`Sprint complete: ${summary.correct}/${summary.goal} correct · ${summary.best_streak} best streak.`);
                practiceActive = false;
                practiceBusy = false;
                return;
            }

            setTimeout(loadNextPracticePrompt, 850);
        });
        return;
    }

    if (actualMorse === expectedMorse) {
        setPracticeFeedback(`Correct: ${target}. Next letter coming up.`);
        recordPracticeResult(target, true).finally(() => {
            setTimeout(loadNextPracticePrompt, 950);
        });
    } else {
        const feedback = getPracticeMode() === "learn"
            ? `Try ${target} again. Follow ${expectedMorse}; I heard ${actualMorse}.`
            : getPracticeMode() === "echo"
            ? `Listen again and echo ${target}: ${expectedMorse}. I heard ${actualMorse}.`
            : `Try ${target} again. I heard ${actualMorse}, but ${target} is ${expectedMorse}.`;
        setPracticeFeedback(feedback);
        recordPracticeResult(target, false).finally(() => {
            setTimeout(retryPracticePrompt, 1200);
        });
    }
}

async function recordPracticeResult(target, correct, answer = "") {
    const panel = getPracticePanel();
    const liveMorse = document.getElementById("liveMorse");
    const mode = getPracticeMode();
    const bonus = getBonusConfig();
    const actualMorse = ["read", "listen"].includes(mode)
        ? ""
        : normalizeMorse(keyboardKeyerActive ? keyboardMorse : (liveMorse ? liveMorse.innerText : ""));

    try {
        const response = await fetch(bonus ? "/bonus/result" : "/practice/result", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                target,
                correct,
                answer,
                mode,
                session_id: bonus ? bonus.sessionId : "",
                expected_morse: panel ? (panel.dataset.expectedMorse || "") : "",
                actual_morse: actualMorse,
                timing_events: keyboardKeyerActive ? keyboardTimingEvents : []
            })
        });
        const data = await response.json();
        updateMorseTimingData(data.timing || null);
        updateProgressPanel(data.progress || []);
        updateScoreCard(data.score || null);
        updateOverallScoreCard(data.overall || null);
        updateBonusScore(data.bonus || null);
        return data;
    } catch (error) {
        console.log("Unable to record practice result", error);
        return null;
    }
}

async function loadNextPracticePrompt() {
    try {
        const bonus = getBonusConfig();
        const response = await fetch(bonus ? "/bonus/next" : `/practice/next?mode=${encodeURIComponent(getPracticeMode())}`, {
            method: "POST"
        });
        const data = await response.json();

        updatePracticePrompt(data.target, data.expected_morse, data.read_choices || []);
        updateMorseTimingData(data.timing || null);
        updateProgressPanel(data.progress || []);
        updateScoreCard(data.score || null);
        updateOverallScoreCard(data.overall || null);
        updateBonusScore(data.bonus || null);
        resetInputDisplay();
        if (bonus) {
            setPracticeFeedback("Next signal. Key it once.");
        } else if (getPracticeMode() === "listen") {
            setPracticeFeedback("Next one. Listen and choose the letter.");
            playPracticePromptInBrowser();
        } else if (getPracticeMode() === "echo") {
            setPracticeFeedback("Next one. Listen, then key it back.");
            playPracticePromptInBrowser();
        } else if (getPracticeMode() === "learn") {
            setPracticeFeedback(`Follow ${data.target}: ${data.expected_morse}.`);
            playPracticePromptInBrowser();
        } else {
            setPracticeFeedback(getPracticeMode() === "read" ? "Next one." : `Now try ${data.target}.`);
        }
        focusReadInput();
    } catch (error) {
        console.log("Unable to load next practice prompt", error);
    } finally {
        practiceBusy = false;
        lastCheckedPracticeMorse = "";
        pendingPracticeMorse = "";
    }
}

async function retryPracticePrompt() {
    try {
        const response = await fetch(`/practice/retry?mode=${encodeURIComponent(getPracticeMode())}`, {
            method: "POST"
        });
        const data = await response.json();

        updatePracticePrompt(data.target, data.expected_morse, data.read_choices || []);
        updateMorseTimingData(data.timing || null);
        updateProgressPanel(data.progress || []);
        updateScoreCard(data.score || null);
        updateOverallScoreCard(data.overall || null);
        resetInputDisplay();
        setPracticeFeedback("Ready. Try it again.");
        if (["listen", "echo", "learn"].includes(getPracticeMode())) {
            playPracticePromptInBrowser();
        }
        focusReadInput();
    } catch (error) {
        console.log("Unable to reset practice prompt", error);
    } finally {
        practiceBusy = false;
        lastCheckedPracticeMorse = "";
        pendingPracticeMorse = "";
    }
}

function updatePracticePrompt(target, expectedMorse, readChoices = []) {
    const panel = getPracticePanel();
    const targetLetter = document.getElementById("targetLetter");
    const expected = document.getElementById("expectedMorse");

    if (!panel || !targetLetter || !expected) {
        return;
    }

    panel.dataset.practiceTarget = target;
    panel.dataset.expectedMorse = expectedMorse;
    if (["send", "learn"].includes(getPracticeMode())) {
        targetLetter.innerText = target;
        expected.innerText = getPracticeMode() === "learn" ? expectedMorse : "?";
    } else if (["listen", "echo"].includes(getPracticeMode())) {
        targetLetter.innerText = "?";
        expected.innerText = "Play Code";
    } else {
        targetLetter.innerText = "?";
        expected.innerText = expectedMorse;
    }

    updateReadChoices(readChoices);
}

function updateReadChoices(choices) {
    const choiceGrid = document.getElementById("readChoices");

    if (!choiceGrid || !Array.isArray(choices) || choices.length === 0) {
        return;
    }

    choiceGrid.innerHTML = "";

    for (const choice of choices) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button secondary read-choice";
        button.dataset.readChoice = choice;
        button.innerText = choice;
        button.addEventListener("click", () => submitReadAnswer(choice));
        choiceGrid.appendChild(button);
    }
}

function updateProgressPanel(progress) {
    const progressPanel = document.getElementById("practiceProgress");

    if (!progressPanel || !Array.isArray(progress)) {
        return;
    }

    for (const item of progress) {
        const row = progressPanel.querySelector(`[data-progress-letter="${item.letter}"]`);

        if (!row) {
            continue;
        }

        const percent = Math.max(0, Math.min(Number(item.strength_percent) || 0, 100));
        const summary = row.querySelector(".progress-row span");
        const bar = row.querySelector(".progress-bar span");
        const meta = row.querySelector(".progress-meta");

        if (summary) {
            summary.innerText = `${percent}%`;
        }

        if (bar) {
            bar.style.width = `${percent}%`;
        }

        if (meta) {
            meta.innerHTML = `
                <span>${item.accuracy}% accuracy</span>
                <span>${item.streak} streak</span>
                <span>${item.attempts} tries</span>
            `;
        }
    }
}

function updateScoreCard(score) {
    if (!score) {
        return;
    }

    const scorePanel = document.getElementById("practiceScore");
    const mastery = document.getElementById("scoreMastery");
    const masteryBar = document.getElementById("scoreMasteryBar");
    const streak = document.getElementById("scoreStreak");
    const accuracy = document.getElementById("scoreAccuracy");
    const attempts = document.getElementById("scoreAttempts");
    const goal = document.getElementById("scoreGoal");

    if (!scorePanel) {
        return;
    }

    const masteryValue = Math.max(0, Math.min(Number(score.mastery) || 0, 100));

    if (mastery) {
        mastery.innerText = `${masteryValue}%`;
    }

    if (masteryBar) {
        masteryBar.style.width = `${masteryValue}%`;
    }

    if (streak) {
        streak.innerText = `current set · ${score.streak} streak`;
    }

    if (accuracy) {
        accuracy.innerText = `${score.accuracy}% accuracy`;
    }

    if (attempts) {
        attempts.innerText = `${score.attempts} tries`;
    }

    if (goal) {
        goal.innerText = masteryValue >= 100
            ? "Mode complete. Go to Daily for the next step."
            : score.next_goal;
    }
}

function updateBonusScore(summary) {
    if (!summary) {
        return;
    }

    const accuracy = document.getElementById("bonusAccuracy");
    const attempts = document.getElementById("bonusAttempts");
    const streak = document.getElementById("bonusStreak");
    const bestStreak = document.getElementById("bonusBestStreak");
    const remaining = document.getElementById("bonusRemaining");

    if (accuracy) {
        accuracy.innerText = `${summary.accuracy}%`;
    }

    if (attempts) {
        attempts.innerText = summary.attempts;
    }

    if (streak) {
        streak.innerText = summary.streak;
    }

    if (bestStreak) {
        bestStreak.innerText = summary.best_streak;
    }

    if (remaining) {
        remaining.innerText = summary.complete ? "Sprint complete" : `${summary.remaining} left`;
    }
}

function updateOverallScoreCard(overall) {
    if (!overall) {
        return;
    }

    const mastery = document.getElementById("overallMastery");
    const masteryBar = document.getElementById("overallMasteryBar");
    const accuracy = document.getElementById("overallAccuracy");
    const attempts = document.getElementById("overallAttempts");
    const streak = document.getElementById("overallStreak");
    const unlockedLetters = document.getElementById("overallUnlockedLetters");
    const learningLetters = document.getElementById("overallLearningLetters");
    const learningProgress = document.getElementById("overallLearningProgress");
    const alphabetProgress = document.getElementById("overallAlphabetProgress");
    const nextUnlock = document.getElementById("overallNextUnlock");
    const masteryValue = Math.max(0, Math.min(Number(overall.current_mastery ?? overall.mastery) || 0, 100));

    if (mastery) {
        mastery.innerText = `${masteryValue}%`;
    }

    if (masteryBar) {
        masteryBar.style.width = `${masteryValue}%`;
    }

    if (accuracy) {
        accuracy.innerText = `${overall.accuracy}% accuracy`;
    }

    if (attempts) {
        attempts.innerText = overall.attempts;
    }

    if (streak) {
        streak.innerText = `${overall.attempts} tries`;
    }

    if (alphabetProgress) {
        alphabetProgress.innerText = overall.alphabet_progress || "";
    }

    if (unlockedLetters && Array.isArray(overall.active_letters)) {
        unlockedLetters.innerHTML = overall.active_letters.map(letter => `<span>${letter}</span>`).join("");
    } else if (unlockedLetters && Array.isArray(overall.unlocked_letters)) {
        unlockedLetters.innerHTML = overall.unlocked_letters.map(letter => `<span>${letter}</span>`).join("");
    }

    if (learningLetters && Array.isArray(overall.learning_letters)) {
        learningLetters.innerHTML = overall.learning_letters.length
            ? overall.learning_letters.map(letter => `<span>${letter}</span>`).join("")
            : "<span>None</span>";
    }

    if (learningProgress) {
        const focus = overall.learning_focus || {};
        if (focus.active) {
            learningProgress.hidden = false;
            learningProgress.innerText = `Learn progress: ${focus.correct}/${focus.goal} · ${focus.remaining} left`;
        } else {
            learningProgress.hidden = true;
            learningProgress.innerText = "";
        }
    }

    if (nextUnlock && overall.next_unlock) {
        const letters = overall.next_unlock.letters || [];
        const learning = overall.learning_letters || [];
        nextUnlock.innerText = learning.length || overall.locked_until_tomorrow
            ? overall.next_goal
            : letters.length
            ? `Next letters after 100% current set: ${letters.join(" ")}`
            : overall.next_unlock.label;
    }
}

function normalizeLetterAnswer(value) {
    return (value || "").trim().toUpperCase().slice(0, 1);
}

function clearReadInput() {
    const input = document.getElementById("readAnswerInput");

    if (input) {
        input.value = "";
    }
}

function focusReadInput() {
    const input = document.getElementById("readAnswerInput");

    if (["read", "listen"].includes(getPracticeMode()) && input) {
        input.focus();
    }
}

function submitReadAnswer(answer) {
    const panel = getPracticePanel();

    if (!panel || !["read", "listen"].includes(getPracticeMode()) || practiceBusy || !practiceActive) {
        return;
    }

    const target = panel.dataset.practiceTarget || "";
    const expectedMorse = panel.dataset.expectedMorse || "";
    const normalizedAnswer = normalizeLetterAnswer(answer);

    if (!normalizedAnswer) {
        return;
    }

    practiceBusy = true;
    clearReadInput();

    if (normalizedAnswer === target) {
        setPracticeFeedback(`Correct: ${target}. Next letter coming up.`);
        recordPracticeResult(target, true, normalizedAnswer).finally(() => {
            setTimeout(loadNextPracticePrompt, 850);
        });
    } else {
        const feedback = getPracticeMode() === "listen"
            ? `Try again. That was ${target}, not ${normalizedAnswer}.`
            : `Try again. ${expectedMorse} is ${target}, not ${normalizedAnswer}.`;
        setPracticeFeedback(feedback);
        recordPracticeResult(target, false, normalizedAnswer).finally(() => {
            setTimeout(retryPracticePrompt, 1200);
        });
    }
}

function resetLiveKeyDisplay() {
    const liveMorse = document.getElementById("liveMorse");
    const liveDecoded = document.getElementById("liveDecoded");

    if (liveMorse) {
        liveMorse.innerText = "Waiting for key...";
    }

    if (liveDecoded) {
        liveDecoded.innerText = "---";
    }
}

function resetInputDisplay() {
    if (keyboardKeyerActive) {
        resetVirtualKeyer();
        return;
    }

    resetLiveKeyDisplay();
}

function resetVirtualKeyer() {
    stopKeyboardTone();
    keyboardPressStartedAt = null;
    keyboardLastReleasedAt = null;
    keyboardMorse = "";
    keyboardTimingEvents = [];
    resetLiveKeyDisplay();
    lastCheckedPracticeMorse = "";
    pendingPracticeMorse = "";

    if (practiceCheckTimer) {
        clearTimeout(practiceCheckTimer);
        practiceCheckTimer = null;
    }

    resetWordAutoCheck();
}

function updateVirtualKeyerDisplay() {
    const liveMorse = document.getElementById("liveMorse");
    const liveDecoded = document.getElementById("liveDecoded");
    const morse = normalizeMorse(keyboardMorse);

    if (liveMorse) {
        liveMorse.innerText = morse || "Waiting for key...";
    }

    if (liveDecoded) {
        liveDecoded.innerText = morse ? (MORSE_DECODE[morse] || "?") : "---";
    }

    schedulePracticeAutoCheck(morse);
    scheduleWordAutoCheck(morse, MORSE_DECODE[morse] || "");
}

function updateKeyboardKeyerToggle() {
    const status = document.getElementById("keyerStatus");

    if (status) {
        status.innerText = "Spacebar keyer";
        status.classList.add("keyboard");
    }
}

function ignoreKeyboardKeyerEvent(event) {
    const tagName = event.target && event.target.tagName;
    return !keyboardKeyerActive && ["INPUT", "TEXTAREA", "BUTTON", "A", "SELECT"].includes(tagName);
}

function handleKeyboardKeyDown(event) {
    if (!keyboardKeyerActive || event.code !== "Space" || event.repeat || ignoreKeyboardKeyerEvent(event)) {
        return;
    }

    event.preventDefault();

    if (keyboardPressStartedAt === null) {
        if (keyboardLastReleasedAt !== null) {
            keyboardTimingEvents.push({
                type: "gap",
                gap_type: "symbol",
                duration_ms: Math.round(performance.now() - keyboardLastReleasedAt)
            });
        }
        keyboardPressStartedAt = performance.now();
        startKeyboardTone();
    }
}

function handleKeyboardKeyUp(event) {
    if (!keyboardKeyerActive || event.code !== "Space" || ignoreKeyboardKeyerEvent(event)) {
        return;
    }

    event.preventDefault();

    if (keyboardPressStartedAt === null) {
        return;
    }

    const durationMs = performance.now() - keyboardPressStartedAt;
    keyboardPressStartedAt = null;
    stopKeyboardTone();
    const symbol = durationMs >= getKeyboardDashThresholdMs() ? "-" : ".";
    keyboardMorse += symbol;
    keyboardTimingEvents.push({
        type: "symbol",
        symbol,
        duration_ms: Math.round(durationMs)
    });
    keyboardLastReleasedAt = performance.now();
    updateVirtualKeyerDisplay();
}

function updatePracticeToggle() {
    const toggle = document.getElementById("practiceToggle");
    const status = document.getElementById("practiceStatus");

    if (!toggle || !status) {
        return;
    }

    toggle.innerText = practiceActive ? "Stop Practice" : "Resume Practice";
    status.innerText = practiceActive ? "Auto practice on" : "Practice paused";
    status.classList.toggle("paused", !practiceActive);
}

function initializePracticeMode() {
    const panel = getPracticePanel();
    const toggle = document.getElementById("practiceToggle");
    const readSubmit = document.getElementById("readSubmit");
    const readInput = document.getElementById("readAnswerInput");
    const listenReplay = document.getElementById("listenReplay");

    if (panel && toggle) {
        toggle.addEventListener("click", () => {
            practiceActive = !practiceActive;

            if (!practiceActive && practiceCheckTimer) {
                clearTimeout(practiceCheckTimer);
                practiceCheckTimer = null;
            }

            updatePracticeToggle();
        });
    }

    document.querySelectorAll("[data-read-choice]").forEach(button => {
        button.addEventListener("click", () => submitReadAnswer(button.dataset.readChoice || ""));
    });

    if (readSubmit && readInput) {
        readSubmit.addEventListener("click", () => submitReadAnswer(readInput.value));
        readInput.addEventListener("keydown", event => {
            if (event.key === "Enter") {
                event.preventDefault();
                submitReadAnswer(readInput.value);
            }
        });
        readInput.addEventListener("input", () => {
            readInput.value = normalizeLetterAnswer(readInput.value);
        });
    }

    if (listenReplay) {
        listenReplay.addEventListener("click", playPracticePromptInBrowser);
    }

    const playLetterButton = document.getElementById("playLetterButton");
    if (playLetterButton) {
        playLetterButton.addEventListener("click", playPracticePromptInBrowser);
    }

    document.querySelectorAll("[data-test-sound]").forEach(button => {
        button.addEventListener("click", testBrowserSound);
    });

    document.querySelectorAll("[data-word-play]").forEach(button => {
        button.addEventListener("click", playWordCard);
    });

    document.querySelectorAll("[data-word-stop]").forEach(button => {
        button.addEventListener("click", stopWordPlayback);
    });

    document.querySelectorAll("[data-word-clear]").forEach(button => {
        button.addEventListener("click", clearKeyInput);
    });

    const stopHereButton = document.getElementById("stopHereButton");
    if (stopHereButton) {
        stopHereButton.addEventListener("click", stopBrowserPlayback);
    }

    document.addEventListener("keydown", handleKeyboardKeyDown);
    document.addEventListener("keyup", handleKeyboardKeyUp);
    window.addEventListener("blur", stopKeyboardTone);

    updatePracticeToggle();
    updateKeyboardKeyerToggle();
    if (panel) {
        clearKeyInput();
    }
    if (panel && ["listen", "echo", "learn"].includes(getPracticeMode())) {
        setPracticeFeedback(getPracticeMode() === "learn"
            ? `Follow ${panel.dataset.practiceTarget}: ${panel.dataset.expectedMorse}.`
            : getPracticeMode() === "echo"
            ? "Listen, then key it back."
            : "Listen and choose the letter.");
        setTimeout(playPracticePromptInBrowser, 350);
    }
    initializeWordPractice();
    focusReadInput();
}

document.addEventListener("DOMContentLoaded", () => {
    initializePracticeMode();
    initializeDailyMissionReward();
});
