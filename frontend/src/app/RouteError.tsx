import { Link, isRouteErrorResponse, useRouteError } from 'react-router'

/** What a screen shows when a route cannot be found or a screen fails: the app's own words and a way back. */
export function RouteError() {
  const error = useRouteError()
  const notFound = isRouteErrorResponse(error) && error.status === 404
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-3 p-8 text-center">
      <h1 className="text-2xl font-semibold">
        {notFound ? 'That page does not exist' : 'Something went wrong'}
      </h1>
      <p className="max-w-xl text-muted-foreground">
        {notFound
          ? 'The address is not one this app knows.'
          : 'This screen could not be shown. Nothing in your library was changed.'}
      </p>
      <Link to="/library" className="underline">
        Back to the library
      </Link>
    </main>
  )
}
