(function(){
  const api=async(url,opts={})=>{opts.headers={...(opts.headers||{}),'X-App-Mode':'operator'};const response=await fetch(url,opts),data=await response.json();if(!response.ok)throw Error(data.error||response.statusText);return data};
  const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const page=(type)=>{
    document.querySelector('#standaloneJobPage')?.remove();
    document.querySelector('.layout')?.classList.add('hidden');
    document.querySelector('#jobsView')?.classList.add('hidden');
    const isStack=type==='stack_generation';
    const host=document.createElement('section');
    host.id='standaloneJobPage';host.className='jobs-view';
    host.innerHTML=`<div class="jobs-head"><div><span class="eyebrow">ADVANCED JOB</span><h2>${isStack?'图片找朋友':'生成缩略图'}</h2><div class="subtle">${isStack?'按相邻照片和 pHash 距离生成 photo stacks':'生成等比例缩小图，供图库浏览和后续特征任务使用'}</div></div></div><div class="job-detail"><div class="job-run-card standalone-job-card"><div class="standalone-fields"><label>处理范围<input id="standaloneFolder" type="text" placeholder="例如：2022/2022_01"></label>${isStack?'<label>最大时间间隔（分钟）<input id="standaloneGap" type="number" min="0.1" step="0.1" value="15"></label><label>pHash Hamming distance<input id="standaloneDistance" type="number" min="0" max="63" step="1" value="20"></label>':''}</div><div class="actions"><button id="standaloneStart" class="primary" type="button">开始</button>${!isStack?'<button id="standaloneCleanStart" class="clean-start" type="button">强行重开</button>':''}<button id="standaloneCancel" type="button" disabled>取消任务</button></div><div class="standalone-progress"><div class="progress-top"><span id="standaloneStage">READY</span><strong id="standalonePercent">0%</strong></div><div class="progress-track"><div id="standaloneProgressFill"></div></div><div class="progress-meta"><span id="standaloneCount">0 / 0</span><span id="standaloneErrors">0 errors</span></div></div><p id="standaloneStatus" class="subtle">默认跳过已有 thumbnail；点击“强行重开”后会全部重建。</p></div><div id="standaloneResults"></div></div>`;
    document.body.append(host);
    const folder=host.querySelector('#standaloneFolder'),start=host.querySelector('#standaloneStart'),cancel=host.querySelector('#standaloneCancel'),cleanStart=host.querySelector('#standaloneCleanStart'),status=host.querySelector('#standaloneStatus'),stage=host.querySelector('#standaloneStage'),percent=host.querySelector('#standalonePercent'),fill=host.querySelector('#standaloneProgressFill'),count=host.querySelector('#standaloneCount'),errors=host.querySelector('#standaloneErrors');
    const setupAutocomplete=async()=>{try{const data=await api('/api/folders');setupFolderAutocomplete(folder,data.folders||[])}catch(error){status.textContent=`目录补全不可用：${error.message}`}};
    setupAutocomplete();
    let jobId=null,timer=null;
    const update=async()=>{if(!jobId)return;const job=await api(`/api/jobs/${jobId}`),detail=job.progress_detail||{},value=Math.max(0,Math.min(100,Number(job.progress)||0)),processed=detail.images_scanned??detail.stage_processed??0,total=detail.images_total??detail.stage_total??0;stage.textContent=String(detail.stage||job.state).toUpperCase();percent.textContent=`${value}%`;fill.style.width=`${value}%`;count.textContent=`${processed} / ${total}`;errors.textContent=`${detail.errors||0} errors`;let text=isStack?`${detail.stacks||0} stacks · pHash ≤ ${detail.max_phash_distance??job.scope.max_phash_distance??'未知'}`:`${detail.thumbnails_created||0} created · ${detail.thumbnails_skipped||0} skipped`;status.textContent=text;if(job.state==='completed'||job.state==='failed'||job.state==='cancelled'){start.disabled=false;cancel.disabled=true;jobId=null;if(timer)clearTimeout(timer);if(job.error)status.textContent+=` · ${job.error}`;return}timer=setTimeout(update,700)};
    if(cleanStart)cleanStart.onclick=()=>{cleanStart.classList.toggle('active');status.textContent=cleanStart.classList.contains('active')?'本次将强制重建全部 thumbnail。':'默认跳过已有 thumbnail。'};
    start.onclick=async()=>{const scope={folder:folder.value.trim()};if(!scope.folder){status.textContent='请填写处理范围';return}if(isStack){scope.max_gap_minutes=Number(host.querySelector('#standaloneGap').value);scope.max_phash_distance=Number(host.querySelector('#standaloneDistance').value)}else scope.clean_start=cleanStart.classList.contains('active');try{const job=await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type,scope})});jobId=job.id;start.disabled=true;cancel.disabled=false;stage.textContent='QUEUED';percent.textContent='0%';fill.style.width='0%';count.textContent='0 / 0';errors.textContent='0 errors';status.textContent='任务已排队';update()}catch(error){status.textContent=error.message}};
    cancel.onclick=async()=>{if(!jobId)return;await api(`/api/jobs/${jobId}/cancel`,{method:'POST'});status.textContent='cancelled';start.disabled=false;cancel.disabled=true;jobId=null};
  };
  window.JobPages={mount:page};
  const thumbnailButton=document.querySelector('#runThumbnailJob');
  const stackingButton=document.querySelector('#runStackJob');
  if(thumbnailButton)thumbnailButton.onclick=()=>{window.location.href='/jobs/thumbnail-generation'};
  if(stackingButton)stackingButton.onclick=()=>{window.location.href='/jobs/stacking'};
})();
