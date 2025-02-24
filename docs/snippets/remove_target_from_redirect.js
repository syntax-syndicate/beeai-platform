let last_location = window.location.href;
let cache = {}

function getTabLink(path) {
    return document.querySelector('a[href="https://docs.crewai.com/examples/example"]');
}


function observeReactMount() {
    const observer = new MutationObserver((mutations, obs) => {
        if (window.location.href !== last_location) {
            cache = {}
            last_location = window.location.href;
        }
        getTabLink().setAttribute("target", "_self")
        console.log('obs')
    });
    observer.observe(document.body, {childList: true, subtree: true});
};

observeReactMount()
