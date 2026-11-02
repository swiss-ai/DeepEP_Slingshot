"""Read the current Slurm allocation deadline, with a conservative fallback."""
import json
import subprocess
import time


def parse_job_deadline(payload, job_id, now):
    jobs = [j for j in payload.get('jobs', []) if str(j.get('job_id')) == str(job_id)]
    if len(jobs) != 1:
        raise ValueError('Slurm did not return exactly the requested job')
    job = jobs[0]
    states = job.get('job_state', [])
    if isinstance(states, str):
        states = [states]
    if states != ['RUNNING']:
        return now, states
    end = job['end_time']
    if isinstance(end, dict):
        if not end.get('set') or end.get('infinite'):
            raise ValueError('Slurm end time is unset or infinite')
        end = end['number']
    end = float(end)
    if end <= 0:
        raise ValueError('Slurm end time is invalid')
    return end, states


def allocation_remaining(environment, now=None, query=None):
    now = time.time() if now is None else now
    info = {'checked_epoch': now, 'exported_end_epoch': environment.get('SLURM_JOB_END_TIME')}
    try:
        job_id = environment['SLURM_JOB_ID']
        if query is None:
            raw = subprocess.check_output(['scontrol', 'show', 'job', job_id, '--json'],
                                          stderr=subprocess.PIPE, timeout=10)
            payload = json.loads(raw.decode())
        else:
            payload = query(job_id)
        deadline, states = parse_job_deadline(payload, job_id, now)
        info.update(source='scontrol current job record', job_state=states, end_epoch=deadline)
    except (KeyError, ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
        info['query_error'] = str(error)
        try:
            deadline = float(environment['SLURM_JOB_END_TIME'])
            info.update(source='exported end time fallback', end_epoch=deadline)
        except (KeyError, ValueError, TypeError):
            deadline = now
            info.update(source='unknown deadline; no test admitted', end_epoch=deadline)
    info['remaining_seconds'] = max(0.0, deadline - now)
    return info
