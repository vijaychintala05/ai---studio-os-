"""Deterministic, clearly fictional snag images and bill PDFs for Inbox testing."""
import argparse,textwrap,hashlib,json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfgen import canvas


def money(paise):
    whole,fraction=divmod(paise,100)
    return f'{whole:,}.{fraction:02d}'


def generate(plan,out):
    out.mkdir(parents=True,exist_ok=True);photos=out/'photos';bills=out/'bills';photos.mkdir(exist_ok=True);bills.mkdir(exist_ok=True)
    try:font=ImageFont.load_default(size=23)
    except TypeError:font=ImageFont.load_default()
    manifest={};vendors={v['key']:v for v in plan['vendors']};projects={p['key']:p for p in plan['projects']}
    def record(key,path,kind,project):
        manifest[key]={'path':str(path.relative_to(out)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'kind':kind,'project':project,'bytes':path.stat().st_size}
    for day in plan['days']:
        for snag in day['snags']:
            path=photos/(snag['key']+'.png');im=Image.new('RGB',(640,480),'#eef2f6');draw=ImageDraw.Draw(im)
            draw.text((22,18),'FICTIONAL TEST IMAGE',font=font,fill='#203047')
            draw.rectangle((170,85,470,405),outline='#394963',width=7)
            draw.line((190,90,190,400),fill='#8494ab',width=5);draw.ellipse((174,210,210,246),outline='#d92f36',width=6)
            draw.line((210,230,350,210),fill='#d92f36',width=4)
            draw.text((25,420),snag['caption'],font=font,fill='#203047')
            draw.text((25,452),f'{snag["project"]} | {snag["severity"]}',font=font,fill='#203047')
            im.save(path,format='PNG',optimize=False);record(snag['key'],path,'snag_photo',snag['project'])
        for tx in day['transactions']:
            if tx.get('channel')!='file' or tx['recipe']=='reversal':continue
            path=bills/(tx['key']+'.pdf');c=canvas.Canvas(str(path),pagesize=(595,842),invariant=1,pageCompression=1)
            c.setTitle('Fictional test bill '+tx['key']);c.setFont('Helvetica-Bold',18);c.drawString(45,790,'FICTIONAL TEST BILL - NOT VALID FOR PAYMENT')
            c.setFont('Helvetica',12)
            vendor=vendors.get(tx.get('vendor'),{})
            rows=[f'Reference: {tx["reference"]}',f'Date: {tx["date"]}',f'Supplier: {vendor.get("name","Fictional test supplier")}',
                  f'GSTIN: {vendor.get("gstin")or"Unregistered fictional supplier"}',f'Project: {projects[tx["project"]]["name"]}',f'Item: {tx["item"]}',
                  f'Net amount: INR {money(tx["amount_paise"])}',f'GST rate: {tx["gst_rate"]} percent ({tx["gst_jurisdiction"]})',
                  f'Total: INR {money(sum(v for v in tx["expected_lines"].values()if v>0))}',f'Settlement: {tx["settlement"]}',
                  'All identities, references and values in this document are invented.']
            for n,text in enumerate(rows):c.drawString(45,745-n*27,text)
            narration=tx['text']+f', on {tx["date"]}, ref {tx["reference"]}'
            for n,line in enumerate(textwrap.wrap('Narration: '+narration,85)):c.drawString(45,365-n*18,line)
            c.showPage();c.save();record(tx['key'],path,'bill',tx['project'])
    (out/'assets.json').write_text(json.dumps(manifest,indent=2,sort_keys=True))
    return {'photos':sum(v['kind']=='snag_photo'for v in manifest.values()),'pdfs':sum(v['kind']=='bill'for v in manifest.values()),'bytes':sum(v['bytes']for v in manifest.values()),'asset_manifest_sha256':hashlib.sha256((out/'assets.json').read_bytes()).hexdigest()}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--plan',default='sim/runtime/generated-v2/plan.json');p.add_argument('--out',default='sim/runtime/assets');a=p.parse_args();print(json.dumps(generate(json.loads(Path(a.plan).read_text()),Path(a.out)),indent=2))
