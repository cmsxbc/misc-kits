/*
Weibo is sooooooooo terrible!
*/

function IWannaForget(class_suffix, root_suffix, limit=10, fcb=()=>console.log('finished!'), reversed=false, offset=0) {
    function Forget(cb, interval) {
        var allWeiboInPage = document.querySelector('div.vue-recycle-scroller__item-wrapper')?.children;
        if (!allWeiboInPage) {
            console.log("There is no weibo, exit!!!");
            return;
        }
        var idx = reversed ? allWeiboInPage.length - 1 - offset: offset;
        if (idx > allWeiboInPage.length - 1 || idx < 0) {
            setTimeout(cb, interval);
            return;
        }
        allWeiboInPage[idx].querySelector(`i.morepop_action_${class_suffix}`).click();
        setTimeout(
            () => {
                var hasDelete = false;
                for (var child of document.querySelector(`.morepop_more_${root_suffix} div.woo-pop-wrap-main`).children) {
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

function IWannaForgetAll(class_suffix, root_suffix, offset=0) {
    const ItemsPreLoop = 10;
    function IWishYouCanBeHappy() {
        window.scrollTo(0, ItemsPreLoop * 1000 * 2);
        setTimeout(() => {
            document.querySelector('i.woo-font--backTop').parentElement.parentElement.click()
            window.scroll(0, 100);
            document.querySelector('div.vue-recycle-scroller__item-wrapper').children[0].focus();
            setTimeout(() => IWannaForget(class_suffix, root_suffix, ItemsPreLoop, IWishYouCanBeHappy, true, offset), 1000);
        }, 10000);
    }
    IWannaForget(class_suffix, root_suffix, ItemsPreLoop, IWishYouCanBeHappy, false, offset);
}

(() => {
    function GetSuffixes(selector, prefix) {
        let suffixes = {}
        for (let action_btn of document.querySelectorAll(selector)) {
            let classList = Array.from(action_btn.classList);
            for (let className of classList) {
                if (!className.startsWith(prefix)) {
                    continue;
                }
                let suffix = className.replace(prefix, "");
                if (suffix in suffixes) {
                    suffixes[suffix] += 1;
                } else {
                    suffixes[suffix] = 1;
                }
            }
        }
        return suffixes;
    }

    let suffixes = GetSuffixes("i.woo-font--angleDown", "morepop_action_");
    let sorted_suffixes = Object.keys(suffixes).sort((a, b) => suffixes[b] - suffixes[a]);
    console.log(suffixes);
    console.log(sorted_suffixes);
    console.log(sorted_suffixes[0]);
    let root_suffixes = GetSuffixes(`.woo-pop-wrap:has(.morepop_action_${sorted_suffixes[0]})`, "morepop_more_");
    console.log(root_suffixes)
    let root_suffix = Object.keys(root_suffixes).sort((a, b) => root_suffixes[b] - root_suffixes[a])[0];
    console.log(root_suffix);
    IWannaForgetAll(sorted_suffixes[0], root_suffix);
})();

