/* 외형만 바꿔요. 경기 API·난수·게임 상태에 접근하지 않아요. */
(function(){
    'use strict';
    var motion=window.matchMedia('(prefers-reduced-motion: reduce)');
    var observer='IntersectionObserver' in window ? new IntersectionObserver(function(entries){entries.forEach(function(e){e.target.classList.toggle('is-offscreen',!e.isIntersecting);});}) : null;
    function load(actor){
        var sheets=Array.from(actor.querySelectorAll('[data-avatar-layer]'));
        var urls=sheets.map(function(el){return el.style.backgroundImage.slice(5,-2);});
        var signature=urls.join('|'); actor._avatarSignature=signature;
        Promise.all(urls.map(function(url){return new Promise(function(resolve,reject){var image=new Image();image.onload=resolve;image.onerror=reject;image.src=url;});})).then(function(){
            if(actor._avatarSignature===signature)actor.classList.remove('is-missing');
        }).catch(function(){if(actor._avatarSignature===signature)actor.classList.add('is-missing');});
    }
    function init(){
        document.querySelectorAll('[data-rk-avatar]').forEach(function(actor){
            if(actor.dataset.avatarReady)return;actor.dataset.avatarReady='1';
            actor.classList.toggle('is-animated',!motion.matches);
            if(observer)observer.observe(actor);load(actor);
        });
        document.querySelectorAll('[data-avatar-picker]').forEach(function(picker){
            if(picker.dataset.avatarReady)return;picker.dataset.avatarReady='1';
            var manifest=JSON.parse(picker.querySelector('#rk-avatar-manifest').textContent);
            var actor=picker.querySelector('[data-rk-avatar]'),state='idle';
            picker.querySelector('[data-avatar-actions]').hidden=false;
            function update(){
                var recipe={};picker.querySelectorAll('[data-avatar-select]').forEach(function(select){recipe[select.dataset.avatarSelect]=select.value;});
                var files=['body-'+recipe.body+'.png','eyes.png',state==='award'?'formal.png':'kit-'+recipe.kit+'.png','hair-'+recipe.hair+'-'+recipe.tone+'.png'];
                if(state!=='award'&&recipe.cap!=='none')files.push('cap-'+recipe.cap+'.png');
                var crop=actor.querySelector('.rk-avatar-crop');crop.replaceChildren();
                files.forEach(function(file){var layer=document.createElement('span');layer.className='rk-avatar-sheet';layer.dataset.avatarLayer='';layer.style.backgroundImage='url("'+manifest.base+file+'")';crop.appendChild(layer);});
                actor.dataset.avatarState=state;
                actor.setAttribute('aria-label',state==='award'?'트로피를 든 선수 아바타':'선수 아바타');
                picker.querySelectorAll('[data-avatar-preview]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.avatarPreview===state));});
                picker.querySelector('[data-avatar-caption]').textContent={idle:'유니폼을 입고 다음 경기를 기다려요.',walk:'같은 외형으로 그라운드를 걸어요.',award:'내 캐릭터가 정장을 입고 트로피를 들어요.'}[state];
                load(actor);
            }
            picker.addEventListener('change',function(event){if(event.target.matches('[data-avatar-select]'))update();});
            picker.addEventListener('click',function(event){var button=event.target.closest('[data-avatar-preview]');if(button){state=button.dataset.avatarPreview;update();}});
        });
    }
    motion.addEventListener('change',function(){document.querySelectorAll('[data-rk-avatar]').forEach(function(actor){actor.classList.toggle('is-animated',!motion.matches);});});
    document.addEventListener('visibilitychange',function(){document.querySelectorAll('[data-rk-avatar]').forEach(function(actor){actor.classList.toggle('is-document-hidden',document.hidden);actor.style.animationPlayState=document.hidden?'paused':'';});});
    init();
    if('MutationObserver' in window)new MutationObserver(function(changes){if(changes.some(function(c){return Array.from(c.addedNodes).some(function(n){return n.nodeType===1&&(n.matches('[data-rk-avatar],[data-avatar-picker]')||n.querySelector('[data-rk-avatar],[data-avatar-picker]'));});}))init();}).observe(document.body,{childList:true,subtree:true});
})();
