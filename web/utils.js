(function(){
  window.setupFolderAutocomplete=(input,folders)=>{
    if(!input)return()=>{};
    const listId=`${input.id}Options`;
    document.getElementById(listId)?.remove();
    const list=document.createElement('datalist');
    list.id=listId;
    (input.closest('label')||document.body).append(list);
    input.setAttribute('list',listId);
    const values=folders||[];
    const refresh=()=>{
      const value=input.value.trim();
      const slash=value.lastIndexOf('/');
      const base=slash>=0?value.slice(0,slash+1):'';
      const partial=(slash>=0?value.slice(slash+1):value).toLowerCase();
      const prefix=base.toLowerCase();
      const options=new Set;
      for(const path of values){
        if(!path.toLowerCase().startsWith(prefix))continue;
        const rest=path.slice(base.length),child=rest.split('/')[0];
        if(child&&child.toLowerCase().startsWith(partial))options.add(base+child);
      }
      list.innerHTML=[...options].sort((a,b)=>a.localeCompare(b)).slice(0,300).map(path=>`<option value="${String(path).replace(/&/g,'&amp;').replace(/"/g,'&quot;')}"></option>`).join('');
    };
    input.addEventListener('input',refresh);
    input.addEventListener('focus',refresh);
    refresh();
    return refresh;
  };
})();
