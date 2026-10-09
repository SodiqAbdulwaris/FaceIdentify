import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Link } from 'react-router'
import { keys } from '@/api/keys'
import type { FaceAnswer } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { CroppedImage } from '../FaceCrop'
import { personLabel } from '../identities/label'
import { errorMessage } from '../library/messages'
import { useObjectUrl } from '../useSourceImage'

const SUPPORTED = ['image/jpeg', 'image/png', 'image/bmp', 'image/webp']
const NOT_SUPPORTED = 'Only JPEG, PNG, BMP and WebP pictures can be searched with.'

/**
 * Search the library with a picture: who might the faces in it be? The picture can be chosen, dropped
 * onto the box, or pasted. It is sent once, nothing is saved (the app remembers neither the picture
 * nor the answer), and every face found gets its own list of possible people. The similarity is a
 * cosine similarity, not a probability: a high one is a reason to look, not proof.
 */
export function FaceSearch() {
  const { endpoints } = useBackend()
  // The picture lives here, not in the query cache: leaving the screen drops it.
  const [picture, setPicture] = useState<{ id: number; file: File } | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const chooser = useRef<HTMLInputElement>(null)
  const url = useObjectUrl(picture?.file)
  // An event that changes a face, a name or an image refreshes this like any search: the old answer
  // is hidden while it is asked again, so a forgotten or deleted person is never left on screen.
  const search = useQuery({
    queryKey: keys.faceSearch(picture?.id ?? 0),
    queryFn: () => endpoints.searchFace((picture as { file: File }).file),
    enabled: picture !== null,
    gcTime: 0,
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const answer = search.isFetching || search.isError ? undefined : search.data

  const take = (file: File | undefined) => {
    if (!file) return
    if (!SUPPORTED.includes(file.type)) {
      setProblem(NOT_SUPPORTED)
      return
    }
    setProblem(null)
    setPicture((previous) => ({ id: (previous?.id ?? 0) + 1, file }))
  }

  useEffect(() => {
    // A picture copied from anywhere (a screenshot, a web page) can be pasted straight in.
    const paste = (event: ClipboardEvent) => {
      const file = [...(event.clipboardData?.files ?? [])].find((f) => f.type.startsWith('image/'))
      if (file) {
        event.preventDefault()
        take(file)
      }
    }
    window.addEventListener('paste', paste)
    return () => window.removeEventListener('paste', paste)
  })

  const drop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    take(event.dataTransfer.files[0])
  }

  return (
    <section aria-label="Search by face" className="flex flex-col gap-3">
      <h2 className="font-medium">Search with a picture</h2>
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={`flex flex-wrap items-center gap-3 rounded-lg border border-dashed p-4 ${
          dragging ? 'bg-accent/40' : ''
        }`}
      >
        <input
          ref={chooser}
          type="file"
          accept={SUPPORTED.join(',')}
          aria-label="Choose a picture"
          className="sr-only"
          onChange={(event) => {
            take(event.target.files?.[0])
            event.target.value = '' // (the same picture can be chosen again)
          }}
        />
        <Button type="button" variant="outline" onClick={() => chooser.current?.click()}>
          Choose a picture
        </Button>
        <p className="min-w-0 text-sm text-muted-foreground">
          or drop one here, or paste one. It is only used for this search and is not saved.
        </p>
      </div>
      {problem ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      <p role="status" aria-live="polite" aria-label="Face search status" className="text-muted-foreground">
        {search.isFetching
          ? 'Looking for faces…'
          : answer
            ? answer.faces.length === 0
              ? 'No face was found in this picture.'
              : `${answer.faces.length} ${answer.faces.length === 1 ? 'face' : 'faces'} found in this picture.`
            : ''}
      </p>
      {search.isError ? (
        <p role="alert" className="text-destructive">
          The picture could not be searched: {errorMessage(search.error)}
        </p>
      ) : null}
      {answer?.faces.map((face) => (
        <Face key={face.index} face={face} url={url} />
      ))}
    </section>
  )
}

const percent = (similarity: number) => similarity.toFixed(2)

function Face({ face, url }: { face: FaceAnswer; url: string | undefined }) {
  const answer = face.identity_answer
  return (
    <section
      aria-label={`Face ${face.index + 1} of the picture`}
      className="flex flex-wrap gap-3 rounded-lg border p-3"
    >
      <CroppedImage url={url} box={face.bounding_box} label={`Face ${face.index + 1}`} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        {answer ? (
          <p className="font-medium">
            Recognised as{' '}
            <Link to={`/identities/${answer.id}`}>{personLabel(answer.id, answer.person)}</Link>
          </p>
        ) : null}
        {face.status === 'UNKNOWN' ? (
          <p>No one in your library resembles this face.</p>
        ) : null}
        {face.status === 'POSSIBLE_PEOPLE' ? (
          <>
            <p className="font-medium">Possible people</p>
            <p className="text-sm text-muted-foreground">
              Nearest first. The similarity is a score of how alike the faces look, not a probability
              that it is the same person.
            </p>
          </>
        ) : null}
        {!face.retrieval_complete ? (
          <p role="status" className="text-sm text-muted-foreground">
            The memory was still catching up, so closer matches may be missing. Try again shortly.
          </p>
        ) : null}
        <ul className="flex flex-col gap-1">
          {face.possible_people.map((p) => (
            <li key={p.identity.id} className="rounded-md border px-3 py-2">
              <Link to={`/identities/${p.identity.id}`}>
                <span className="font-medium">{personLabel(p.identity.id, p.identity.person)}</span>{' '}
                <span className="text-sm text-muted-foreground">
                  similarity {percent(p.similarity)} · {p.matching_faces} matching{' '}
                  {p.matching_faces === 1 ? 'face' : 'faces'} · {p.identity.source_count}{' '}
                  {p.identity.source_count === 1 ? 'image' : 'images'}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
