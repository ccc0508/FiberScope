"""Render one private PDF page in a bounded process for coordinate review."""
from pathlib import Path
import sys
from uuid import uuid4


def main():
    import pypdfium2 as pdfium
    pdf=pdfium.PdfDocument(sys.argv[1])
    page_no=int(sys.argv[2])
    if not 1<=page_no<=len(pdf)<=200:
        raise ValueError('invalid_page')
    page=pdf[page_no-1]
    if page.get_width()>3000 or page.get_height()>3000:
        raise ValueError('unsupported_page_size')
    output=Path(sys.argv[3])
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_name(uuid4().hex+'.png')
    bitmap=page.render(scale=1.5)
    bitmap.to_pil().save(temp)
    temp.replace(output)
    bitmap.close();page.close();pdf.close()


if __name__=='__main__':
    main()
