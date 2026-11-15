/** Nonblocking, progressive-enhancement navigation for research model home screens.
 * Same in-page filter UX as the original / homepage, with real href fallbacks.
 * Preserves viewport and horizontal rail positions; never changes predictions.
 */
export const HOME_INTERACTION_SCRIPT = String.raw`(function(){
 var serial=0;
 function isHome(url){return /^\/models\/(6m|96m)\/?$/.test(url.pathname);}
 function showVenue(a,url){
   var venue=a.getAttribute("data-model-venue"),root=document.getElementById("model-page-root");
   if(!venue||!root)return false;
   var current=new URL(location.href);
   if(current.pathname!==url.pathname ||
      (current.searchParams.get("date")||"")!==(url.searchParams.get("date")||""))return false;
   root.querySelectorAll("[data-model-venue]").forEach(function(x){
     var active=x.getAttribute("data-model-venue")===venue;
     x.classList.toggle("active",active);
     if(active)x.setAttribute("aria-current","true");else x.removeAttribute("aria-current");
   });
   root.querySelectorAll(".venue-section[data-venue]").forEach(function(x){
     x.hidden=x.getAttribute("data-venue")!==venue;
   });
   history.pushState({},"",url.pathname+url.search);
   return true;
 }
 async function load(url,push){
   var id=++serial,old=document.getElementById("model-page-root");
   if(!old)return;
   var y=window.scrollY,rails={};
   old.querySelectorAll("[data-model-rail]").forEach(function(x){
     rails[x.getAttribute("data-model-rail")]=x.scrollLeft;
   });
   old.setAttribute("aria-busy","true");
   try{
     var response=await fetch(url.pathname+url.search,{cache:"no-store",headers:{"accept":"text/html"}});
     if(!response.ok)throw Error("HTTP "+response.status);
     var doc=new DOMParser().parseFromString(await response.text(),"text/html");
     var next=doc.getElementById("model-page-root");
     if(!next)throw Error("MODEL_PAGE_MISSING");
     if(id!==serial)return;
     old.replaceWith(next);
     document.title=doc.title;
     Object.keys(rails).forEach(function(key){
       var rail=[].find.call(next.querySelectorAll("[data-model-rail]"),
         function(x){return x.getAttribute("data-model-rail")===key;});
       if(rail)rail.scrollLeft=rails[key];
     });
     if(push)history.pushState({},"",url.pathname+url.search);
     window.scrollTo(0,y);
     requestAnimationFrame(function(){window.scrollTo(0,y);});
   }catch(e){
     if(id!==serial)return;
     old.removeAttribute("aria-busy");
     var status=old.querySelector(".model-nav-error");
     if(status){status.hidden=false;status.textContent="切り替えに失敗しました。再度選択してください。";}
   }
 }
 document.addEventListener("click",function(e){
   if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
   if(!(e.target instanceof Element))return;
   var a=e.target.closest("a[data-model-filter],a[data-prediction-model]");
   if(!a||a.target||a.hasAttribute("download"))return;
   var url=new URL(a.href,location.href);
   if(url.origin!==location.origin||!isHome(url))return;
   e.preventDefault();
   if(a.hasAttribute("data-model-venue")&&showVenue(a,url))return;
   load(url,true);
 });
 window.addEventListener("popstate",function(){
   var url=new URL(location.href);
   if(isHome(url))load(url,false);
 });
})();`;
