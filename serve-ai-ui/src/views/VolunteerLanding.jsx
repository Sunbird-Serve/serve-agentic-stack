/**
 * eVidyaloka - Volunteer Landing Page
 * Volunteer-first entry point with mission-driven messaging
 */
import { ArrowRight, Heart, BookOpen, Users } from 'lucide-react';
import { Button } from '../components/ui/button';

const HERO_IMAGE = 'https://images.unsplash.com/photo-1497375638960-ca368c7231e4?w=1200&q=80';

export const VolunteerLanding = ({ onStartJourney }) => {
  return (
    <div className="min-h-screen bg-white" data-testid="volunteer-landing">
      {/* Hero Section */}
      <div className="relative">
        {/* Background Image with Overlay */}
        <div className="absolute inset-0 h-[70vh]">
          <img
            src={HERO_IMAGE}
            alt="Children learning in rural India classroom"
            className="w-full h-full object-cover"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/30 to-white" />
        </div>

        {/* Header */}
        <header className="relative z-10 px-6 py-4">
          <div className="max-w-6xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-white/90 backdrop-blur flex items-center justify-center shadow-lg">
                <BookOpen className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white drop-shadow-md">
                  eVidyaloka
                </h1>
                <p className="text-xs text-white/80">Serve</p>
              </div>
            </div>
          </div>
        </header>

        {/* Hero Content */}
        <div className="relative z-10 px-6 pt-16 pb-32 min-h-[60vh] flex items-center">
          <div className="max-w-6xl mx-auto w-full">
            <div className="max-w-2xl">
              <h2 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-white mb-6 leading-tight drop-shadow-lg">
                Help a child learn,
                <br />
                <span className="text-amber-300">change a life</span>
              </h2>
              <p className="text-lg sm:text-xl text-white/90 mb-8 leading-relaxed drop-shadow-md max-w-xl">
                Join thousands of volunteers bringing quality education to children 
                in rural India. Your time and knowledge can open doors that were 
                never there before.
              </p>
              <Button
                size="lg"
                onClick={onStartJourney}
                className="bg-amber-500 hover:bg-amber-600 text-white text-lg px-8 py-6 rounded-full shadow-xl hover:shadow-2xl transition-all duration-300 group"
                data-testid="start-journey-btn"
              >
                Start your volunteer journey
                <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
              </Button>
            </div>
          </div>
        </div>
      </div>

      {/* Impact Stats */}
      <div className="relative z-10 -mt-16 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="bg-white rounded-2xl shadow-xl p-8 grid grid-cols-3 gap-8">
            <div className="text-center">
              <div className="text-3xl sm:text-4xl font-bold text-slate-900 mb-1">10,000+</div>
              <div className="text-sm text-slate-500">Children Supported</div>
            </div>
            <div className="text-center border-x border-slate-200">
              <div className="text-3xl sm:text-4xl font-bold text-slate-900 mb-1">500+</div>
              <div className="text-sm text-slate-500">Active Volunteers</div>
            </div>
            <div className="text-center">
              <div className="text-3xl sm:text-4xl font-bold text-slate-900 mb-1">200+</div>
              <div className="text-sm text-slate-500">Villages Reached</div>
            </div>
          </div>
        </div>
      </div>

      {/* How It Works */}
      <div className="px-6 py-20">
        <div className="max-w-4xl mx-auto">
          <h3 className="text-2xl sm:text-3xl font-bold text-slate-900 text-center mb-4">
            How you can help
          </h3>
          <p className="text-slate-600 text-center mb-12 max-w-2xl mx-auto">
            Getting started is simple. In just a few minutes, you'll be on your way 
            to making a real difference in a child's education.
          </p>

          <div className="grid sm:grid-cols-3 gap-8">
            <div className="text-center group">
              <div className="w-16 h-16 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4 group-hover:bg-amber-200 transition-colors">
                <span className="text-2xl font-bold text-amber-600">1</span>
              </div>
              <h4 className="font-semibold text-slate-900 mb-2">Tell us about yourself</h4>
              <p className="text-sm text-slate-500">
                Share your skills, interests, and availability through a friendly conversation.
              </p>
            </div>

            <div className="text-center group">
              <div className="w-16 h-16 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4 group-hover:bg-amber-200 transition-colors">
                <span className="text-2xl font-bold text-amber-600">2</span>
              </div>
              <h4 className="font-semibold text-slate-900 mb-2">Get matched</h4>
              <p className="text-sm text-slate-500">
                We'll connect you with students who can benefit most from what you offer.
              </p>
            </div>

            <div className="text-center group">
              <div className="w-16 h-16 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-4 group-hover:bg-amber-200 transition-colors">
                <span className="text-2xl font-bold text-amber-600">3</span>
              </div>
              <h4 className="font-semibold text-slate-900 mb-2">Start teaching</h4>
              <p className="text-sm text-slate-500">
                Begin your journey of helping children learn, grow, and dream bigger.
              </p>
            </div>
          </div>

          <div className="text-center mt-12">
            <Button
              onClick={onStartJourney}
              className="bg-amber-500 hover:bg-amber-600 text-white px-8 py-3 rounded-full"
              data-testid="start-journey-btn-secondary"
            >
              Begin now
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </div>
        </div>
      </div>

      {/* Testimonial / Quote */}
      <div className="bg-slate-50 px-6 py-16">
        <div className="max-w-3xl mx-auto text-center">
          <Heart className="w-10 h-10 text-amber-500 mx-auto mb-6" />
          <blockquote className="text-xl sm:text-2xl text-slate-700 italic mb-6 leading-relaxed">
            "The best thing about volunteering with eVidyaloka is seeing a child's 
            eyes light up when they finally understand something. That moment makes 
            everything worth it."
          </blockquote>
          <p className="text-slate-500">— Priya, Volunteer since 2022</p>
        </div>
      </div>

      {/* Footer */}
      <footer className="px-6 py-8 border-t border-slate-200">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <BookOpen className="w-5 h-5 text-amber-600" />
            <span className="font-semibold text-slate-900">eVidyaloka</span>
          </div>
          <p className="text-sm text-slate-500">
            Enabling equitable access to quality education for children in rural India
          </p>
        </div>
      </footer>
    </div>
  );
};

export default VolunteerLanding;
