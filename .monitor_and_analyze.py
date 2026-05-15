import time, os, sys, re, json, subprocess
# Ler PID do arquivo criado ao iniciar o bot
pid = None
if os.path.exists('.last_bot_pid'):
    try:
        with open('.last_bot_pid', 'r') as f:
            pid = int(f.read().strip())
    except Exception:
        pid = None

# Log atual (após correções)
logfile = 'test_diagnostic_after_fix_60m.log'
if pid is None:
    print('PID nao encontrado em .last_bot_pid; abortando monitor')
    sys.exit(1)
summary = {'by_symbol':{}, 'overall':{}}
print('Monitor started for PID', pid)
# wait until process exits using tasklist
while True:
    try:
        res = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True)
        if str(pid) in res.stdout:
            time.sleep(5)
            continue
        else:
            break
    except Exception as e:
        print('tasklist check failed:', e)
        time.sleep(5)
# process ended
print('Process ended, analyzing log...')
if not os.path.exists(logfile):
    print('Log file not found:', logfile); sys.exit(1)
pattern_bot = re.compile(r"^(?:\[.*\])?\s*INFO\s+bot\s+\s*(.+?)\s+\| Fluxo de Liquidez BLOQUEADO \| etapa=(\d) \| motivo=(.+)$")
pattern_reason = re.compile(r"reason=([^\n]+)")
with open(logfile, 'r', encoding='utf-8', errors='replace') as f:
    for line in f:
        m = pattern_bot.search(line)
        if m:
            symbol = m.group(1).strip()
            motivo = m.group(3).strip()
            summary['by_symbol'].setdefault(symbol, {})
            summary['by_symbol'][symbol].setdefault(motivo, 0)
            summary['by_symbol'][symbol][motivo] += 1
        else:
            mr = pattern_reason.search(line)
            if mr:
                reason = mr.group(1).strip()
                summary['overall'].setdefault(reason, 0)
                summary['overall'][reason] += 1
# write JSON
with open('diagnostic_summary_60m.json', 'w', encoding='utf-8') as out:
    json.dump(summary, out, indent=2, ensure_ascii=False)
print('Summary written to diagnostic_summary_60m.json')
# also print a brief top counts
print('Overall counts:')
for k,v in sorted(summary['overall'].items(), key=lambda x:-x[1]):
    print(f'{v:5d}  {k}')
print('\nTop symbols with blocks:')
for sym,counts in sorted(summary['by_symbol'].items(), key=lambda x:-sum(x[1].values()))[:20]:
    total = sum(counts.values())
    print(f'{sym:12s} {total:3d}  {counts}')
