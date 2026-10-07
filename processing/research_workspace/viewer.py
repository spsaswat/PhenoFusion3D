"""Offline WebGL inspection and exact-source-index endpoint annotation."""
import base64
import html
import json
import numpy as np
from processing.rgb_recovery.viewer import TEMPLATE


def write_viewer(out, records, specimen_ids, manifest):
    from .workflow import link, save_json
    tags=['<script>const DATA=[];</script>'];metadata=[]
    for index,record in enumerate(records.values()):
        p=record['points'];c=record['colours'];centre=(p.min(0)+p.max(0))/2
        span=max(float(np.ptp(p,axis=0).max()),1e-9)
        stride=max(1,int(np.ceil(len(p)/600000)));ids=np.arange(0,len(p),stride,dtype='<u4')
        if len(p)>np.iinfo(np.uint32).max:raise ValueError('Point reviewer supports fewer than 2^32 points per source')
        data=dict(id=record['id'],label=record['label'],context=record['context'],sha256=record['sha256'],
            count=len(ids),original_count=len(p),span=1.,display_stride=stride,
            centre=centre.tolist(),scale=span,download=link(record['path'],out),
            xyz=base64.b64encode(((p[ids]-centre)/span).astype('<f4').tobytes()).decode(),
            rgb=base64.b64encode(np.rint(np.clip(c[ids],0,1)*255).astype('u1').tobytes()).decode(),
            source_indices=base64.b64encode(ids.tobytes()).decode())
        file=f'research_cloud_{index}.js';(out/file).write_text('DATA.push('+json.dumps(data)+');\n',encoding='utf-8')
        tags.append(f'<script src="{file}"></script>')
        metadata.append({k:v for k,v in data.items() if k not in ('xyz','rgb','source_indices')})
    page=TEMPLATE.replace('__CLOUDS__','null').replace('__SUMMARY__','{}')
    page=page.replace('const DATA=null,SUMMARY=','const SUMMARY=').replace('<script>\nconst SUMMARY=','\n'.join(tags)+'\n<script>\nconst SUMMARY=')
    page=page.replace('Plant · reconstruction review','Research point and endpoint review').replace('Plant reconstruction review','Point and endpoint review')
    page=page.replace('Offline reconstruction · inspect all sides before measurements','Double-click a visible point to mark an endpoint · all measurements remain candidates')
    page=page.replace('<option value="0">Reconstructed point cloud</option>',
        ''.join(f'<option value="{i}">{html.escape(r["label"])}</option>' for i,r in enumerate(records.values())))
    a=page.index('<div class="label">Original reference photograph</div>');b=page.index('</aside>',a)
    specimens=''.join(f'<option>{html.escape(p)}</option>' for p in specimen_ids)
    page=page[:a]+f'''<div class="label">Mark a measurement</div><p>Use the original scene for a base missing from a cleaned cloud. Source-visible tissue and specimen identity must be reviewed. Point picks do not confirm physical scale.</p>
<label for="target-plant">Measured specimen</label><select id="target-plant">{specimens}</select>
<label for="quantity">Quantity</label><select id="quantity"><option value="observed_chord">Observed tissue distance (may be partial)</option><option value="height">Height: base → highest tip</option><option value="leaf_chord_length">Leaf: blade base → tip (straight)</option><option value="leaf_section_width">Leaf: two edges of one width section</option></select>
<div class="grid" style="margin-top:8px"><button id="mark-first">Mark first point</button><button id="mark-second">Mark second point</button></div>
<p id="pick-status" role="status">Choose an endpoint, then double-click a visible source point.</p>
<button id="save-measurement">Keep endpoint pair</button><p id="pair-count">0 pairs queued</p>
<button id="download-annotations">Download endpoint JSON</button>
<p>Import this JSON in the Research workspace tab to calculate candidate values. Marked pairs are unreviewed by default. Straight blade chords and photographed width sections are distinct from curved midrib length and maximum leaf width.</p>
<a class="download" id="cloud-download" href="{html.escape(metadata[0]['download'],quote=True)}" download>Open original source cloud</a><a class="download" href="index.html">Back to research report</a>
<footer>Source point indices and hashes identify exact existing vertices; the preview may sample points for speed. No interpolated point is saved. Select missing bases only where actually present in a source cloud. Closer visual fitting and brightness affect display only.</footer>
'''+page[b:]
    a=page.index('<dialog id="photo">');b=page.index('</dialog>',a)+len('</dialog>');page=page[:a]+page[b:]
    page=page.replace("document.getElementById('source').onclick=()=>document.getElementById('photo').showModal();document.getElementById('close').onclick=()=>document.getElementById('photo').close();",'')
    page=page.replace('let yaw=Math.PI,pitch=25','let yaw=0,pitch=25').replace('function reset(){yaw=Math.PI;','function reset(){yaw=0;')
    page=page.replace('zoom=1,pan=','zoom=1.1,pan=').replace('zoom=1;pan=','zoom=1.1;pan=')
    page=page.replace('<button data-y="180" data-e="25">Front</button>','<button data-y="0" data-e="25">Front</button>').replace('<button data-y="0" data-e="25">Back</button>','<button data-y="180" data-e="25">Back</button>')
    a=page.index('function info(){');b=page.index("document.getElementById('model').onchange",a)
    page=page[:a]+'''function info(){const d=DATA[current];
document.getElementById('count').textContent=d.original_count.toLocaleString()+' source points';
document.getElementById('badge').textContent=d.label;
document.getElementById('details').textContent=(d.context?'Original scene context. ':'Reviewed specimen candidate. ')+d.count.toLocaleString()+' displayed points; source index stride '+d.display_stride+'. Bases/tips may be absent. Cloud bounds do not define anatomical height.';
document.getElementById('cloud-download').href=d.download;}
'''+page[b:]
    additions=r'''
const cpu=DATA.map(d=>({xyz:new Float32Array(bytes(d.xyz).buffer),ids:new Uint32Array(bytes(d.source_indices).buffer)}));
const definitions={observed_chord:'straight_distance_between_observed_points',height:'vertical_stem_base_to_highest_tip',leaf_chord_length:'straight_blade_base_to_tip_chord',leaf_section_width:'straight_width_at_identified_section'};
let activeEndpoint=null,endpoints=[null,null],queued=[];
const pickStatus=document.getElementById('pick-status');
document.getElementById('mark-first').onclick=()=>{activeEndpoint=0;pickStatus.textContent='Double-click the first endpoint on visible tissue.'};
document.getElementById('mark-second').onclick=()=>{activeEndpoint=1;pickStatus.textContent='Double-click the second endpoint on visible tissue.'};
function clearPair(){endpoints=[null,null];activeEndpoint=null;pickStatus.textContent='Endpoint pair cleared for the new specimen or quantity.'}
document.getElementById('target-plant').onchange=clearPair;document.getElementById('quantity').onchange=clearPair;
canvas.addEventListener('dblclick',e=>{
 if(activeEndpoint===null)return;
 const rect=canvas.getBoundingClientRect(),w=rect.width,h=rect.height,mx=e.clientX-rect.left,my=e.clientY-rect.top;
 const r=[Math.cos(yaw),Math.sin(yaw),0],u=[-Math.sin(yaw)*Math.sin(pitch),Math.cos(yaw)*Math.sin(pitch),Math.cos(pitch)],t=[Math.sin(yaw)*Math.cos(pitch),-Math.cos(yaw)*Math.cos(pitch),Math.sin(pitch)];
 const sx=2*zoom/1.22*Math.min(h/w,1),sy=2*zoom/1.22*Math.min(w/h,1),arr=cpu[current].xyz;
 let chosen=-1,best=64,closest=-Infinity;
 for(let i=0;i<arr.length;i+=3){
  const x=arr[i],y=arr[i+1],z=arr[i+2];
  const px=((x*r[0]+y*r[1]+z*r[2])*sx+pan[0]+1)*w/2;
  const py=(1-((x*u[0]+y*u[1]+z*u[2])*sy+pan[1]))*h/2;
  const depth=x*t[0]+y*t[1]+z*t[2];if(Math.abs(depth*.7)>1)continue;
  const distance=(px-mx)**2+(py-my)**2;
  // Same approximately one-pixel screen bin: prefer the visible front point.
  if(distance<best-1 || (distance<=best+1 && distance<=64 && depth>closest)){
   chosen=i/3;best=distance;closest=depth;
  }
 }
 if(chosen<0){pickStatus.textContent='No displayed point within 8 pixels. Zoom or change view; no point was invented.';return}
 const d=DATA[current];endpoints[activeEndpoint]={cloud_id:d.id,source_sha256:d.sha256,point_index:Number(cpu[current].ids[chosen])};
 pickStatus.textContent='Endpoint '+(activeEndpoint+1)+': '+d.label+', source point '+endpoints[activeEndpoint].point_index+'. Review this location before using the pair.';
 activeEndpoint=null;
});
document.getElementById('save-measurement').onclick=()=>{
 if(!endpoints[0]||!endpoints[1]){pickStatus.textContent='Mark both endpoints first.';return}
 if(endpoints[0].cloud_id===endpoints[1].cloud_id&&endpoints[0].point_index===endpoints[1].point_index){pickStatus.textContent='Endpoints must be different source points.';return}
 const trait=document.getElementById('quantity').value;
 queued.push({specimen_id:document.getElementById('target-plant').value,trait,definition:definitions[trait],points:endpoints.map(p=>({...p})),landmarks_reviewed:false,organ_match_confirmed:false,reference_id:null});
 document.getElementById('pair-count').textContent=queued.length+' endpoint pairs queued';clearPair();
};
document.getElementById('download-annotations').onclick=()=>{
 const doc={schema_version:1,source:'offline_source_index_point_review',review_status:'unreviewed_endpoint_candidates',measurements:queued};
 const blob=new Blob([JSON.stringify(doc,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download='research_endpoints.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
'''
    page=page.replace('</script></html>',additions+'\n</script></html>')
    (out/'point_review.html').write_text(page,encoding='utf-8')
    save_json(out/'point_review_provenance.json',dict(models=metadata,display_only=True,
        endpoint_status='unreviewed source point candidates',geometry_created=False,
        source_files_modified=False,coordinate_unit=manifest.get('coordinate_unit','unknown')))
