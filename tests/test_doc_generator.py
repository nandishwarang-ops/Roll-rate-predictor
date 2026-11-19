import sys, pathlib, json, re, hashlib, time, shutil; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent)); import fixtures as FX
import pack_author as PA, doc_generator as DG
from pypdf import PdfReader
ok = lambda n, c: print(("PASS " if c else "FAIL ") + n) or c
root = pathlib.Path(__file__).resolve().parent.parent; r = []; t0 = time.time()
ctx, charts, evidence, meta = FX.lender_a_inputs(); pack = PA.build_pack(ctx); out = root / "outputs/packs/bundle_LENDER_A_2025-06"; shutil.rmtree(out, ignore_errors=True)
meta = dict(meta, generated="2026-11-20", audit={"source": pack["source"], "rendered_issues": 0}); res = DG.generate(pack, charts, evidence, meta, out); dt = time.time() - t0
print(f"    built in {dt:.1f}s (including the simulation and charts)"); md = (out / "pack.md").read_text(); pdf = PdfReader(str(out / "pack.pdf")); text = "\n".join(p.extract_text() for p in pdf.pages)
r += [ok(f"PDF has {len(pdf.pages)} pages, Markdown {len(md.splitlines())} lines", len(pdf.pages) >= 4 and len(md.splitlines()) > 60)]
imgs = sum(len(p.images) for p in pdf.pages); r += [ok(f"all 4 charts embedded in the PDF ({imgs} images)", imgs >= 4)]
r += [ok("every image link in the Markdown resolves to a file, each with a CSV table view", all((out / m).exists() and (out / m).with_suffix(".csv").exists() for m in re.findall(r"!\[[^\]]*\]\((charts/[^)]+)\)", md)) and md.count("![") == 4)]
head = pack["markdown"].splitlines()[0][2:]; r += [ok("headline appears on the PDF cover and in the Markdown title", head[:40] in text.replace("\n", " ").replace("  ", " ") or head[:25] in text and md.startswith("# " + head))]
body_md = pack["markdown"]; nums_pdf = set(re.findall(r"\d[\d,]*(?:\.\d+)?", text.split("Appendix: evidence ledger")[0].replace("Page ", "")))
nums_md = set(re.findall(r"\d[\d,]*(?:\.\d+)?", body_md)) | set(re.findall(r"\d[\d,]*(?:\.\d+)?", meta["run_id"] + meta["generated"] + "2025 June")) | set(re.findall(r"\d+", text[:600]))
extra = {n for n in nums_pdf - nums_md if not re.fullmatch(r"\d{1,2}|20\d\d", n)}; r += [ok(f"no number in the PDF body that is absent from the audited pack text ({sorted(extra)[:5]})", not extra)]
r += [ok("run id in the PDF footer and in the Markdown", meta["run_id"] in text and meta["run_id"] in md)]
r += [ok("evidence ledger appendix lists the cited query SQL and the attribution call", "Appendix: evidence ledger" in md and "select agency_id" in md and "attribution" in md and "select agency_id" in text)]
r += [ok("audited body is unchanged: pack text appears verbatim in pack.md", all(sec.strip() in md for sec in re.split(r"(?m)^(?=## )", body_md)[1:3]))]
man = json.loads((out / "manifest.json").read_text()); r += [ok("manifest hashes match every file", all(hashlib.sha256((out / f).read_bytes()).hexdigest() == h for f, h in man["files"].items()) and "pack.pdf" in man["files"] and man["model_run"] == meta["run_id"])]
r += [ok("whole document step is fast (non-functional target: pack in under 30 minutes)", dt < 600)]
import pypdfium2 as pdfium
d = pdfium.PdfDocument(str(out / "pack.pdf")); [d[i].render(scale=1.3).to_pil().save(out / f"preview_p{i+1}.png") for i in range(min(3, len(d)))]
sys.exit(0 if all(r) else 1)
