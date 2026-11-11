"""Kepala tabel bertingkat yang sama untuk layar, ponsel, dan PDF."""


def susun(kolom):
    paths=[[c[k] for k in ('kelompok','subkelompok','nama') if c.get(k)] for c in kolom]
    depth=max((len(p) for p in paths),default=1)
    rows=[]
    for level in range(depth):
        cells=[];i=0
        while i<len(paths):
            path=paths[i]
            if level>=len(path):i+=1;continue
            leaf=level==len(path)-1
            j=i+1
            if not leaf:
                while j<len(paths) and len(paths[j])>level+1 and paths[j][:level+1]==path[:level+1]:j+=1
            cells.append(dict(nama=path[level],mulai=i,kolom=j-i,baris=depth-level if leaf else 1))
            i=j
        rows.append(cells)
    return rows
