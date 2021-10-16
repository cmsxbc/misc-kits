/*
Douyin is terrible,
Douyin on web is a little better,
but what if it's auto? (the buildin autoplay is not functional)
*/

(async function IWannaABGM(lengthLimit, repeatLimit) {
    window.IWannaABGMRunning = true;
    lengthLimit = lengthLimit ?? 30;
    repeatLimit = repeatLimit ?? 2;

    function getCurVideo() {
        return document.getElementsByClassName('swiper-slide-active')[0]
                       .getElementsByTagName('video')[0];
    }

    function disableOfficalAutoPlay() {
        let button = document.getElementsByClassName('swiper-slide-active')[0]
                .getElementsByClassName('xgplayer-autoplay-setting')[0]
                .getElementsByTagName('button')[0];
        if (button.className.indexOf("checked") != -1) {
            button.click();
        }
    }

    function nextVideo() {
        document.getElementsByClassName('xgplayer-playswitch-next')[0].click();
    }

    function now() {
        return (new Date()).getTime() / 1000;
    }

    function sleep(ms) {
        return new Promise(_ => setTimeout(_, ms));
    }

    disableOfficalAutoPlay();

    let state = {
        video: getCurVideo(),
        freshTime: now()
    }

    function hasfreshedVideo() {
        return getCurVideo().src !== state.video.src
    }

    function updateState() {
        state.video = getCurVideo();
        state.freshTime = now();
    }

    async function nextVideoLoop(reason) {
        console.log(`next video because ${reason}`);
        nextVideo();
        do {
            await sleep(500);
        } while (!hasfreshedVideo());
        updateState();
    }

    async function repeatVideoLoop() {
        let duration;
        do {
            if (hasfreshedVideo()) {
                updateState();
            }
            duration = now() - state.freshTime;
            console.log('duration', duration, duration / state.video.duration, repeatLimit);
            await sleep(1000);
        } while (duration / state.video.duration < repeatLimit);
    }

    while (window.IWannaABGMRunning) {
        while (state.video.duration > lengthLimit) {
            await nextVideoLoop(`too long: ${state.video.duration} > ${lengthLimit}`);
        }
        await repeatVideoLoop();
        await nextVideoLoop('auto switch');
    }
})();
