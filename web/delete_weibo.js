/*
Weibo is sooooooooo terrible!
*/

function IWannaForget(class_suffix, limit=10, fcb=()=>console.log('finished!'), reversed=false, offset=0) {
    function Forget(cb, interval) {
        var allWeiboInPage = document.querySelector('div.vue-recycle-scroller__item-wrapper').children,
            idx = reversed ? allWeiboInPage.length - 1 - offset: offset;
        if (idx > allWeiboInPage.length - 1 || idx < 0) {
            setTimeout(cb, interval);
            return;
        }
        allWeiboInPage[idx].querySelector(`i.morepop_action_${class_suffix}`).click();
        setTimeout(
            () => {
                var hasDelete = false;
                for (var child of document.querySelector('div.woo-pop-wrap-main').children) {
                    if (child.innerText == '\u5220\u9664') {
                        child.click();
                        hasDelete = true;
                        break;
                    }
                }
                if (!hasDelete) {
                    console.log("There is no delete, exit!!!");
                    return;
                }
                setTimeout(
                    () => {
                        document.querySelector('div.woo-dialog-ctrl').children[1].click();
                        setTimeout(cb, interval);
                    },
                    2000
                );
            },
            1000
        );
    }

    function Loop() {
        if (limit > 0) {
            console.log(`delete ${limit}`);
            limit -= 1;
            Forget(Loop, 3000);
        } else {
            fcb();
        }
    }
    Loop();
}

function IWannaForgetAll(class_suffix, offset=0) {
    const ItemsPreLoop = 10;
    function IWishYouCanBeHappy() {
        window.scrollTo(0, ItemsPreLoop * 1000 * 2);
        setTimeout(() => {
            document.querySelector('i.woo-font--backTop').parentElement.parentElement.click()
            window.scroll(0, 100);
            document.querySelector('div.vue-recycle-scroller__item-wrapper').children[0].focus();
            setTimeout(() => IWannaForget(class_suffix, ItemsPreLoop, IWishYouCanBeHappy, true, offset), 1000);
        }, 10000);
    }
    IWannaForget(class_suffix, ItemsPreLoop, IWishYouCanBeHappy, false, offset);
}

(function IWillHelpYouForgetAll() {
    let suffixes = {}
    for (let action_btn of document.querySelectorAll("i.woo-font--angleDown")) {
        let classList = Array.from(action_btn.classList);
        for (let className of classList) {
            if (!className.startsWith("morepop_action_")) {
                continue;
            }
            let suffix = className.replace("morepop_action_", "");
            if (suffix in suffixes) {
                suffixes[suffix] += 1;
            } else {
                suffixes[suffix] = 1;
            }
        }
    }
    let sorted_suffixes = Object.keys(suffixes).sort((a, b) => suffixes[b] - suffixes[a]);
    console.log(suffixes, sorted_suffixes);
    IWannaForgetAll(sorted_suffixes[0]);
})();

